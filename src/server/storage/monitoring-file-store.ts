import "server-only";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, extname, join, resolve } from "node:path";
import { z } from "zod";
import { storedFileSchema, type FileKind, type StoredFile } from "@/contracts/monitoring-files";
import { DEFAULT_PROJECT_ID } from "@/contracts/access";
import { atomicJson, withFileLock } from "@/server/storage/atomic";
import {
  ensureSupabaseProject,
  supabaseContext,
  supabaseStorageError,
} from "@/server/storage/supabase-context";

/**
 * 上传文件存储层（local / Supabase 双 Provider）
 * ==============================================
 *
 * 目录布局（默认 `<repo>/var/uploads/`，可用 `EXCAVAGUARD_UPLOAD_ROOT` 覆盖）：
 *
 *     var/uploads/
 *     ├── index.json                     元数据索引
 *     ├── monitoring/<file_id><ext>      监测数据文件
 *     └── standard/<file_id>/standard.json   用户规范（**独立目录**）
 *
 * 为什么用户规范要放独立目录：`StandardsRegistry(user_dir=...)` 按**目录**加载全部
 * `*.json`。每次上传放进自己的目录，判定时只加载"本次上传的那一份"，
 * 不会把历史上传的规范混进同一次比对。
 *
 * 安全约束
 * --------
 * - **落盘文件名一律由 `file_id` 生成**，不使用用户提供的文件名 —— 杜绝路径穿越；
 *   原始文件名只作为元数据保存，用于界面展示。
 * - 扩展名白名单 + 体积上限，超限即拒收。
 * - 内容指纹（SHA-256）随元数据保存，用于确认"分析的就是上传的那份"。
 *
 * Supabase 对象路径同样只使用 project_id、kind、file_id 与固定文件名；Python
 * 读取前下载到随机临时目录并核验指纹，调用后清理。Provider 必须显式配置。
 */

export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024; // 20 MB

export const MONITORING_EXTENSIONS = [".csv", ".tsv", ".txt", ".xlsx", ".xlsm"] as const;
export const STANDARD_EXTENSIONS = [".json"] as const;

const MEDIA_TYPES: Record<string, string> = {
  ".csv": "text/csv",
  ".tsv": "text/tab-separated-values",
  ".txt": "text/plain",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
  ".json": "application/json",
};

/** 索引内部记录：比对外契约多一个相对路径字段，不对外暴露。 */
type IndexRecord = StoredFile & { stored_rel_path: string };

const INDEX_VERSION = 1;

export class StorageError extends Error {
  readonly code:
    | "UNSUPPORTED_FILE_TYPE"
    | "FILE_TOO_LARGE"
    | "FILE_EMPTY"
    | "FILE_NOT_FOUND"
    | "STORAGE_ERROR";

  constructor(code: StorageError["code"], message: string) {
    super(message);
    this.name = "StorageError";
    this.code = code;
  }
}

function uploadRoot(): string {
  const custom = process.env.EXCAVAGUARD_UPLOAD_ROOT?.trim();
  return custom ? resolve(custom) : resolve(process.cwd(), "var", "uploads");
}

function indexPath(): string {
  return join(uploadRoot(), "index.json");
}

/** 存储 provider 解析。切换必须显式配置，避免意外迁移数据。 */
export function getStorageProvider(): "local" | "supabase" {
  const declared = process.env.EXCAVAGUARD_STORAGE_PROVIDER?.trim().toLowerCase();
  if (declared === "supabase") return "supabase";
  if (declared && declared !== "local") {
    throw new StorageError("STORAGE_ERROR", "不支持该存储 provider。");
  }
  return "local";
}

async function readIndex(): Promise<IndexRecord[]> {
  try {
    const raw = await readFile(indexPath(), "utf-8");
    const parsed = z.strictObject({
      version: z.literal(INDEX_VERSION),
      files: z.array(storedFileSchema.extend({
        stored_rel_path: z.string().regex(/^(monitoring\/[0-9a-f-]{36}\.(csv|tsv|txt|xlsx|xlsm)|standard\/[0-9a-f-]{36}\/standard\.json)$/),
      })),
    }).parse(JSON.parse(raw));
    return parsed.files;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw new StorageError("STORAGE_ERROR", "上传元数据索引不可读取或已损坏。");
  }
}

async function writeIndex(records: IndexRecord[]): Promise<void> {
  await mkdir(uploadRoot(), { recursive: true });
  await atomicJson(indexPath(), { version: INDEX_VERSION, files: records });
}

/** 只对外暴露契约字段，内部路径不外泄。 */
function toPublic(record: IndexRecord): StoredFile {
  return {
    file_id: record.file_id,
    project_id: record.project_id ?? DEFAULT_PROJECT_ID,
    kind: record.kind,
    original_name: record.original_name,
    size_bytes: record.size_bytes,
    media_type: record.media_type,
    sha256: record.sha256,
    created_at: record.created_at,
    storage: record.storage,
  };
}

function allowedExtensions(kind: FileKind): readonly string[] {
  return kind === "monitoring" ? MONITORING_EXTENSIONS : STANDARD_EXTENSIONS;
}

function safeExtension(kind: FileKind, originalName: string): string {
  const ext = extname(originalName).toLowerCase();
  const allowed = allowedExtensions(kind);
  if (!allowed.includes(ext)) {
    throw new StorageError(
      "UNSUPPORTED_FILE_TYPE",
      `不支持的文件类型 ${ext || "（无扩展名）"}；允许：${allowed.join("、")}。`,
    );
  }
  return ext;
}

/** 落盘相对路径。**完全由 file_id 生成**，不含用户输入。统一用 `/` 分隔。 */
function relativePathFor(kind: FileKind, fileId: string, ext: string): string {
  return kind === "monitoring"
    ? `monitoring/${fileId}${ext}`
    : `standard/${fileId}/standard${ext}`;
}

type SupabaseFileRow = {
  file_id: string;
  project_id: string;
  kind: FileKind;
  original_name: string;
  storage_path: string;
  size_bytes: number;
  media_type: string;
  sha256: string;
  created_at: string;
};

export type MaterializedFile = {
  path: string;
  cleanup: () => Promise<void>;
};

function toSupabasePublic(row: SupabaseFileRow): StoredFile {
  const createdAt = new Date(row.created_at);
  if (!Number.isFinite(createdAt.getTime())) {
    throw new StorageError("STORAGE_ERROR", "Supabase 文件元数据时间不合法。");
  }
  return storedFileSchema.parse({
    file_id: row.file_id,
    project_id: row.project_id,
    kind: row.kind,
    original_name: row.original_name,
    size_bytes: row.size_bytes,
    media_type: row.media_type,
    sha256: row.sha256,
    created_at: createdAt.toISOString(),
    storage: "supabase",
  });
}

async function getSupabaseRow(fileId: string): Promise<SupabaseFileRow | null> {
  const { client } = supabaseContext();
  const { data, error } = await client
    .from("excavaguard_files")
    .select("file_id,project_id,kind,original_name,storage_path,size_bytes,media_type,sha256,created_at")
    .eq("file_id", fileId)
    .maybeSingle();
  if (error) throw supabaseStorageError("Supabase 文件元数据读取失败", error);
  return data as SupabaseFileRow | null;
}

async function saveSupabaseFile(input: {
  kind: FileKind;
  originalName: string;
  bytes: Uint8Array;
  mediaType?: string;
  projectId: string;
}): Promise<StoredFile> {
  const ext = safeExtension(input.kind, input.originalName);
  const fileId = randomUUID();
  const fileName = input.kind === "monitoring" ? `monitoring${ext}` : "standard.json";
  const storagePath = `${input.projectId}/${input.kind}/${fileId}/${fileName}`;
  const mediaType = input.mediaType?.trim() || MEDIA_TYPES[ext] || "application/octet-stream";
  const sha256 = createHash("sha256").update(input.bytes).digest("hex");
  const createdAt = new Date().toISOString();
  const { client, bucket } = supabaseContext();
  await ensureSupabaseProject(input.projectId);

  const { error: uploadError } = await client.storage
    .from(bucket)
    .upload(storagePath, input.bytes, { contentType: mediaType, upsert: false });
  if (uploadError) throw supabaseStorageError("Supabase 文件上传失败", uploadError);

  const { data, error: metadataError } = await client
    .from("excavaguard_files")
    .insert({
      file_id: fileId,
      project_id: input.projectId,
      kind: input.kind,
      original_name: input.originalName,
      storage_path: storagePath,
      size_bytes: input.bytes.byteLength,
      media_type: mediaType,
      sha256,
      created_at: createdAt,
    })
    .select("file_id,project_id,kind,original_name,storage_path,size_bytes,media_type,sha256,created_at")
    .single();
  if (metadataError) {
    const { error: cleanupError } = await client.storage.from(bucket).remove([storagePath]);
    const suffix = cleanupError ? `；对象清理失败：${cleanupError.message}` : "";
    throw supabaseStorageError("Supabase 文件元数据写入失败", {
      message: `${metadataError.message}${suffix}`,
    });
  }
  return toSupabasePublic(data as SupabaseFileRow);
}

export async function saveFile(input: {
  kind: FileKind;
  originalName: string;
  bytes: Uint8Array;
  mediaType?: string;
  projectId?: string;
}): Promise<StoredFile> {
  const provider = getStorageProvider();
  const { kind, originalName, bytes } = input;

  const name = originalName.trim();
  if (!name) {
    throw new StorageError("UNSUPPORTED_FILE_TYPE", "文件名不能为空。");
  }
  if (bytes.byteLength === 0) {
    throw new StorageError("FILE_EMPTY", "文件内容为空。");
  }
  if (bytes.byteLength > MAX_UPLOAD_BYTES) {
    throw new StorageError(
      "FILE_TOO_LARGE",
      `文件 ${(bytes.byteLength / 1024 / 1024).toFixed(1)} MB 超过上限 ` +
        `${MAX_UPLOAD_BYTES / 1024 / 1024} MB。`,
    );
  }
  if (provider === "supabase") {
    return saveSupabaseFile({
      kind,
      originalName: name,
      bytes,
      mediaType: input.mediaType,
      projectId: input.projectId ?? DEFAULT_PROJECT_ID,
    });
  }

  const ext = safeExtension(kind, name);
  const fileId = randomUUID();
  const rel = relativePathFor(kind, fileId, ext);
  const abs = join(uploadRoot(), rel);

  try {
    await mkdir(dirname(abs), { recursive: true });
    await writeFile(abs, bytes);
  } catch (error) {
    throw new StorageError(
      "STORAGE_ERROR",
      `写入文件失败：${error instanceof Error ? error.message : String(error)}`,
    );
  }

  const record: IndexRecord = {
    file_id: fileId,
    project_id: input.projectId ?? DEFAULT_PROJECT_ID,
    kind,
    original_name: name,
    size_bytes: bytes.byteLength,
    media_type: input.mediaType?.trim() || MEDIA_TYPES[ext] || "application/octet-stream",
    sha256: createHash("sha256").update(bytes).digest("hex"),
    created_at: new Date().toISOString(),
    storage: "local",
    stored_rel_path: rel.split("\\").join("/"),
  };

  await withFileLock(`${indexPath()}.lock`, async () => {
    const records = await readIndex();
    records.push(record);
    await writeIndex(records);
  });
  return toPublic(record);
}

export async function listFiles(kind?: FileKind, projectId?: string): Promise<StoredFile[]> {
  if (getStorageProvider() === "supabase") {
    const { client } = supabaseContext();
    let query = client
      .from("excavaguard_files")
      .select("file_id,project_id,kind,original_name,storage_path,size_bytes,media_type,sha256,created_at")
      .order("created_at", { ascending: false });
    if (kind) query = query.eq("kind", kind);
    if (projectId) query = query.eq("project_id", projectId);
    const { data, error } = await query;
    if (error) throw supabaseStorageError("Supabase 文件列表读取失败", error);
    return (data as SupabaseFileRow[]).map(toSupabasePublic);
  }
  const records = await readIndex();
  const filtered = records.filter((record) =>
    (!kind || record.kind === kind) &&
    (!projectId || (record.project_id ?? DEFAULT_PROJECT_ID) === projectId),
  );
  // 新上传的排在前面
  return filtered
    .slice()
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
    .map(toPublic);
}

export async function getFile(fileId: string): Promise<StoredFile | null> {
  if (getStorageProvider() === "supabase") {
    const row = await getSupabaseRow(fileId);
    return row ? toSupabasePublic(row) : null;
  }
  const records = await readIndex();
  const hit = records.find((r) => r.file_id === fileId);
  return hit ? toPublic(hit) : null;
}

/** 取得本地绝对路径（引擎以子进程方式按路径读取）。找不到时返回 null。 */
export async function localPathOf(fileId: string): Promise<string | null> {
  if (getStorageProvider() === "supabase") {
    throw new StorageError(
      "STORAGE_ERROR",
      "Supabase 文件必须通过 materializeStoredFile() 获取临时路径并清理。",
    );
  }
  const records = await readIndex();
  const hit = records.find((r) => r.file_id === fileId);
  if (!hit) return null;
  const abs = join(uploadRoot(), hit.stored_rel_path);
  try {
    const info = await stat(abs);
    if (!info.isFile()) return null;
    const bytes = await readFile(abs);
    if (bytes.byteLength !== hit.size_bytes ||
        createHash("sha256").update(bytes).digest("hex") !== hit.sha256) {
      throw new StorageError("STORAGE_ERROR", "上传文件指纹不一致，请重新上传。");
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw new StorageError("STORAGE_ERROR", "上传文件缺失、不可读或指纹不一致，请重新上传。");
  }
  return abs;
}

/** 用户规范所在目录（交给 `StandardsRegistry(user_dir=...)`）。 */
export async function standardDirOf(fileId: string): Promise<string | null> {
  const abs = await localPathOf(fileId);
  return abs ? join(abs, "..") : null;
}

/** 为 Python 引擎提供已校验的本地文件租约；调用方必须在 finally 中 cleanup。 */
export async function materializeStoredFile(fileId: string): Promise<MaterializedFile | null> {
  if (getStorageProvider() === "local") {
    const path = await localPathOf(fileId);
    return path ? { path, cleanup: async () => undefined } : null;
  }

  const row = await getSupabaseRow(fileId);
  if (!row) return null;
  const { client, bucket } = supabaseContext();
  const { data, error } = await client.storage.from(bucket).download(row.storage_path);
  if (error || !data) {
    throw supabaseStorageError("Supabase 文件下载失败", error ?? { message: "响应为空" });
  }
  const bytes = new Uint8Array(await data.arrayBuffer());
  if (bytes.byteLength !== row.size_bytes ||
      createHash("sha256").update(bytes).digest("hex") !== row.sha256) {
    throw new StorageError("STORAGE_ERROR", "Supabase 文件与元数据指纹不一致，停止处理。");
  }

  const directory = await mkdtemp(join(tmpdir(), "excavaguard-file-"));
  const ext = safeExtension(row.kind, row.original_name);
  const path = join(directory, row.kind === "standard" ? `standard${ext}` : `${row.file_id}${ext}`);
  try {
    await writeFile(path, bytes, { mode: 0o600 });
  } catch (error) {
    await rm(directory, { recursive: true, force: true });
    throw new StorageError(
      "STORAGE_ERROR",
      `Supabase 临时文件写入失败：${error instanceof Error ? error.message : String(error)}`,
    );
  }
  return {
    path,
    cleanup: async () => {
      await rm(directory, { recursive: true, force: true });
    },
  };
}

/** 清空全部上传（仅用于测试与本地重置）。返回删除的索引条数。 */
export async function clearAll(): Promise<number> {
  if (getStorageProvider() === "supabase") {
    throw new StorageError("STORAGE_ERROR", "禁止通过本地测试重置接口清空 Supabase。");
  }
  return withFileLock(`${indexPath()}.lock`, async () => {
    const records = await readIndex();
    await writeIndex([]);
    return records.length;
  });
}

/** 供测试确认目录确实存在且可写。 */
export async function storageRootInfo(): Promise<{
  root: string;
  provider: "local" | "supabase";
  file_count: number;
  subdirs: string[];
}> {
  if (getStorageProvider() === "supabase") {
    const { client } = supabaseContext();
    const { count, error } = await client
      .from("excavaguard_files")
      .select("*", { count: "exact", head: true });
    if (error) throw supabaseStorageError("Supabase 文件统计失败", error);
    return {
      root: "supabase://excavaguard_files",
      provider: "supabase",
      file_count: count ?? 0,
      subdirs: [],
    };
  }
  const root = uploadRoot();
  await mkdir(root, { recursive: true });
  let subdirs: string[] = [];
  try {
    const entries = await readdir(root, { withFileTypes: true });
    subdirs = entries.filter((e) => e.isDirectory()).map((e) => e.name);
  } catch {
    subdirs = [];
  }
  return { root, provider: getStorageProvider(), file_count: (await readIndex()).length, subdirs };
}
