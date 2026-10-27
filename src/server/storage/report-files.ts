import "server-only";
import { createHash, randomUUID } from "node:crypto";
import { readFile, realpath, rm } from "node:fs/promises";
import { extname, resolve } from "node:path";
import type { ReportArtifact, ReportDraft } from "@/contracts/agent-runtime";
import { AppError } from "@/server/api/errors";
import { getStorageProvider } from "@/server/storage/monitoring-file-store";
import {
  ensureSupabaseProject,
  isUniqueViolation,
  supabaseContext,
  supabaseStorageError,
} from "@/server/storage/supabase-context";

type SupabaseReportRow = {
  artifact_id: string;
  draft_id: string;
  run_id: string;
  project_id: string;
  kind: ReportArtifact["kind"];
  file_name: string;
  storage_path: string;
  media_type: string;
  sha256: string;
  size_bytes: number;
  created_at: string;
};

function draftIdOf(artifact: ReportArtifact): string {
  const draftId = artifact.relative_path.split("/")[2];
  if (!draftId) throw new AppError(500, "STORAGE_ERROR", "报告草稿路径缺少草稿 ID。");
  return draftId;
}

function assertContent(artifact: ReportArtifact, bytes: Uint8Array): void {
  if (
    bytes.byteLength !== artifact.size_bytes ||
    createHash("sha256").update(bytes).digest("hex") !== artifact.sha256
  ) {
    throw new AppError(409, "ARTIFACT_CHANGED", "报告文件与已审计指纹不一致，停止下载与接受。");
  }
}

async function readLocalReportFile(artifact: ReportArtifact): Promise<Buffer> {
  const path = resolve(
    process.cwd(),
    "var",
    "report-artifacts",
    draftIdOf(artifact),
    artifact.file_name,
  );
  let bytes: Buffer;
  try {
    // Mapped Windows drives / a symlinked workspace can name the same root.
    // Canonicalize that root, while still rejecting links beneath it.
    const canonicalRoot = await realpath(process.cwd());
    const expectedPath = resolve(canonicalRoot, "var", "report-artifacts", draftIdOf(artifact), artifact.file_name);
    if (await realpath(path) !== expectedPath) throw new Error("symlink");
    bytes = await readFile(path);
  } catch {
    throw new AppError(404, "FILE_NOT_FOUND", "报告产物不存在、路径不一致或不可读取。");
  }
  assertContent(artifact, bytes);
  return bytes;
}

async function reportRow(
  draftId: string,
  kind: ReportArtifact["kind"],
): Promise<SupabaseReportRow | null> {
  const { client } = supabaseContext();
  const { data, error } = await client
    .from("excavaguard_report_artifacts")
    .select("artifact_id,draft_id,run_id,project_id,kind,file_name,storage_path,media_type,sha256,size_bytes,created_at")
    .eq("draft_id", draftId)
    .eq("kind", kind)
    .maybeSingle();
  if (error) throw supabaseStorageError("Supabase 报告元数据读取失败", error);
  return data as SupabaseReportRow | null;
}

function assertReportRow(row: SupabaseReportRow, artifact: ReportArtifact): void {
  if (
    row.file_name !== artifact.file_name ||
    row.media_type !== artifact.media_type ||
    row.sha256 !== artifact.sha256 ||
    row.size_bytes !== artifact.size_bytes
  ) {
    throw new AppError(409, "ARTIFACT_CHANGED", "Supabase 报告元数据与当前已审计草稿不一致。");
  }
}

async function readSupabaseReportFile(artifact: ReportArtifact): Promise<Buffer> {
  const row = await reportRow(draftIdOf(artifact), artifact.kind);
  if (!row) throw new AppError(404, "FILE_NOT_FOUND", "Supabase 中不存在当前报告产物。");
  assertReportRow(row, artifact);
  const { client, bucket } = supabaseContext();
  const { data, error } = await client.storage.from(bucket).download(row.storage_path);
  if (error || !data) {
    throw supabaseStorageError("Supabase 报告文件下载失败", error ?? { message: "响应为空" });
  }
  const bytes = Buffer.from(await data.arrayBuffer());
  assertContent(artifact, bytes);
  return bytes;
}

export async function readReportFile(artifact: ReportArtifact): Promise<Buffer> {
  return getStorageProvider() === "supabase"
    ? readSupabaseReportFile(artifact)
    : readLocalReportFile(artifact);
}

export async function verifyReportFiles(draft: ReportDraft): Promise<void> {
  for (const artifact of draft.artifacts) await readReportFile(artifact);
}

/** 审计通过后上传三件套并写元数据；全部云端校验通过后才清理本地渲染副本。 */
export async function persistReportFiles(
  runId: string,
  projectId: string,
  draft: ReportDraft,
): Promise<void> {
  if (getStorageProvider() === "local") return;
  await ensureSupabaseProject(projectId);
  const { client, bucket } = supabaseContext();
  const draftId = draft.ref.artifact_id;

  for (const artifact of draft.artifacts) {
    const existing = await reportRow(draftId, artifact.kind);
    if (existing) {
      if (existing.run_id !== runId || existing.project_id !== projectId) {
        throw new AppError(409, "ARTIFACT_CHANGED", "Supabase 报告产物归属与当前运行不一致。");
      }
      assertReportRow(existing, artifact);
      continue;
    }

    const bytes = await readLocalReportFile(artifact);
    const suffix = extname(artifact.file_name);
    const storagePath = `${projectId}/report/${draftId}/${artifact.kind}${suffix}`;
    const { error: uploadError } = await client.storage
      .from(bucket)
      .upload(storagePath, bytes, { contentType: artifact.media_type, upsert: false });
    let uploadedNow = false;
    if (uploadError) {
      if (!uploadError.message.toLowerCase().includes("already exists")) {
        throw supabaseStorageError("Supabase 报告文件上传失败", uploadError);
      }
      const { data: existingObject, error: downloadError } = await client.storage
        .from(bucket)
        .download(storagePath);
      if (downloadError || !existingObject) {
        throw supabaseStorageError(
          "Supabase 已存在报告文件校验失败",
          downloadError ?? { message: "响应为空" },
        );
      }
      assertContent(artifact, new Uint8Array(await existingObject.arrayBuffer()));
    } else {
      uploadedNow = true;
    }

    const { error: metadataError } = await client
      .from("excavaguard_report_artifacts")
      .insert({
        artifact_id: randomUUID(),
        draft_id: draftId,
        run_id: runId,
        project_id: projectId,
        kind: artifact.kind,
        file_name: artifact.file_name,
        storage_path: storagePath,
        media_type: artifact.media_type,
        sha256: artifact.sha256,
        size_bytes: artifact.size_bytes,
      });
    if (metadataError && !isUniqueViolation(metadataError)) {
      const { error: cleanupError } = uploadedNow
        ? await client.storage.from(bucket).remove([storagePath])
        : { error: null };
      const suffixMessage = cleanupError ? `；对象清理失败：${cleanupError.message}` : "";
      throw supabaseStorageError("Supabase 报告元数据写入失败", {
        message: `${metadataError.message}${suffixMessage}`,
      });
    }
    const stored = await reportRow(draftId, artifact.kind);
    if (!stored) throw new AppError(500, "STORAGE_ERROR", "Supabase 报告元数据写入后不可读取。");
    assertReportRow(stored, artifact);
  }

  await verifyReportFiles(draft);
  await rm(resolve(process.cwd(), "var", "report-artifacts", draftId), {
    recursive: true,
    force: true,
  });
}
