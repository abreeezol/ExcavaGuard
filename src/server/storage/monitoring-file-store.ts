import "server-only";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import { dirname, extname, join, resolve } from "node:path";
import type { FileKind, StoredFile } from "@/contracts/monitoring-files";

/**
 * 上传文件存储层（本地文件系统实现）
 * ====================================
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
 * 生产路径
 * --------
 * 本实现面向本地开发与演示。生产环境应替换为对象存储
 * （`.env.example` 已预留 `SUPABASE_URL` / `SUPABASE_STORAGE_BUCKET`）。
 * 该适配器**尚未实现**：没有可用的 bucket 与元数据表，无法验证，
 * 因此不提供"看起来能跑"的空壳实现。切换方式见 `getStorageProvider()`。
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

/** 存储 provider 解析。当前只实现了 local。 */
export function getStorageProvider(): "local" | "supabase" {
  const declared = process.env.EXCAVAGUARD_STORAGE_PROVIDER?.trim().toLowerCase();
  if (declared === "supabase") {
    throw new StorageError(
      "STORAGE_ERROR",
      "supabase 存储适配器尚未实现（缺少 bucket 与元数据表，无法验证）。" +
        "请使用 EXCAVAGUARD_STORAGE_PROVIDER=local。",
    );
  }
  return "local";
}

async function readIndex(): Promise<IndexRecord[]> {
  try {
    const raw = await readFile(indexPath(), "utf-8");
    const parsed = JSON.parse(raw) as { version?: number; files?: IndexRecord[] };
    return Array.isArray(parsed.files) ? parsed.files : [];
  } catch {
    // 索引不存在或损坏时按空处理：文件仍在磁盘上，不丢数据
    return [];
  }
}

async function writeIndex(records: IndexRecord[]): Promise<void> {
  await mkdir(uploadRoot(), { recursive: true });
  await writeFile(
    indexPath(),
    JSON.stringify({ version: INDEX_VERSION, files: records }, null, 2),
    "utf-8",
  );
}

/** 只对外暴露契约字段，内部路径不外泄。 */
function toPublic(record: IndexRecord): StoredFile {
  return {
    file_id: record.file_id,
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

export async function saveFile(input: {
  kind: FileKind;
  originalName: string;
  bytes: Uint8Array;
  mediaType?: string;
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
    kind,
    original_name: name,
    size_bytes: bytes.byteLength,
    media_type: input.mediaType?.trim() || MEDIA_TYPES[ext] || "application/octet-stream",
    sha256: createHash("sha256").update(bytes).digest("hex"),
    created_at: new Date().toISOString(),
    storage: provider,
    stored_rel_path: rel.split("\\").join("/"),
  };

  const records = await readIndex();
  records.push(record);
  await writeIndex(records);
  return toPublic(record);
}

export async function listFiles(kind?: FileKind): Promise<StoredFile[]> {
  const records = await readIndex();
  const filtered = kind ? records.filter((r) => r.kind === kind) : records;
  // 新上传的排在前面
  return filtered
    .slice()
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
    .map(toPublic);
}

export async function getFile(fileId: string): Promise<StoredFile | null> {
  const records = await readIndex();
  const hit = records.find((r) => r.file_id === fileId);
  return hit ? toPublic(hit) : null;
}

/** 取得本地绝对路径（引擎以子进程方式按路径读取）。找不到时返回 null。 */
export async function localPathOf(fileId: string): Promise<string | null> {
  const records = await readIndex();
  const hit = records.find((r) => r.file_id === fileId);
  if (!hit) return null;
  const abs = join(uploadRoot(), hit.stored_rel_path);
  try {
    await stat(abs);
  } catch {
    return null;
  }
  return abs;
}

/** 用户规范所在目录（交给 `StandardsRegistry(user_dir=...)`）。 */
export async function standardDirOf(fileId: string): Promise<string | null> {
  const abs = await localPathOf(fileId);
  return abs ? join(abs, "..") : null;
}

/** 清空全部上传（仅用于测试与本地重置）。返回删除的索引条数。 */
export async function clearAll(): Promise<number> {
  const records = await readIndex();
  await writeIndex([]);
  return records.length;
}

/** 供测试确认目录确实存在且可写。 */
export async function storageRootInfo(): Promise<{
  root: string;
  provider: "local" | "supabase";
  file_count: number;
  subdirs: string[];
}> {
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
