import "server-only";
import { readFile, readdir } from "node:fs/promises";
import { join, resolve } from "node:path";
import { z } from "zod";
import { persistedRunSchema, type PersistedRun, type RunSummary } from "@/contracts/runs";
import type { LocalAccess } from "@/contracts/access";
import { AppError } from "@/server/api/errors";
import { atomicJson } from "@/server/storage/atomic";
import { getStorageProvider } from "@/server/storage/monitoring-file-store";
import {
  ensureSupabaseProject,
  isUniqueViolation,
  supabaseContext,
  supabaseStorageError,
} from "@/server/storage/supabase-context";

type SupabaseRunRow = {
  run_id: string;
  revision: number;
  project_id: string;
  record: unknown;
  created_at: string;
};

function root(): string {
  getStorageProvider();
  const custom = process.env.EXCAVAGUARD_RUN_ROOT?.trim();
  // 运行记录属于运行时挂载数据，不能作为构建依赖打包。
  return custom ? resolve(/* turbopackIgnore: true */ custom) : resolve(process.cwd(), "var", "runs");
}

function runDirectory(runId: string): string {
  if (!z.uuid().safeParse(runId).success) throw new AppError(400, "INVALID_REQUEST", "运行标识不合法。");
  return join(/* turbopackIgnore: true */ root(), runId);
}

async function revisions(runId: string): Promise<number[]> {
  const directory = runDirectory(runId);
  try {
    return (await readdir(/* turbopackIgnore: true */ directory))
      .filter((name) => /^[1-9]\d*\.json$/.test(name))
      .map((name) => Number(name.slice(0, -5)))
      .sort((left, right) => right - left);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw new AppError(500, "STORAGE_ERROR", "运行目录不可读取。");
  }
}

function parseSupabaseRun(row: SupabaseRunRow): PersistedRun {
  const record = persistedRunSchema.parse(row.record);
  if (
    record.run_id !== row.run_id ||
    record.revision !== row.revision ||
    record.project_id !== row.project_id
  ) {
    throw new AppError(500, "STORAGE_ERROR", "Supabase 运行记录标识不一致。");
  }
  return record;
}

async function readSupabaseRun(runId: string, access: LocalAccess): Promise<PersistedRun> {
  if (!z.uuid().safeParse(runId).success) {
    throw new AppError(400, "INVALID_REQUEST", "运行标识不合法。");
  }
  const { client } = supabaseContext();
  const { data, error } = await client
    .from("excavaguard_run_revisions")
    .select("run_id,revision,project_id,record,created_at")
    .eq("run_id", runId)
    .eq("project_id", access.project_id)
    .order("revision", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw supabaseStorageError("Supabase 运行记录读取失败", error);
  if (!data) throw new AppError(404, "RUN_NOT_FOUND", "运行记录不存在。");
  const record = parseSupabaseRun(data as SupabaseRunRow);
  if (record.owner_id !== access.owner_id) {
    throw new AppError(404, "RUN_NOT_FOUND", "运行记录不存在。");
  }
  return record;
}

async function saveSupabaseRun(
  next: PersistedRun,
  expectedRevision: number,
): Promise<PersistedRun> {
  const { client } = supabaseContext();
  const { data: latest, error: latestError } = await client
    .from("excavaguard_run_revisions")
    .select("revision")
    .eq("run_id", next.run_id)
    .order("revision", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (latestError) throw supabaseStorageError("Supabase 运行版本读取失败", latestError);
  if ((latest?.revision ?? 0) !== expectedRevision) {
    throw new AppError(409, "RUN_CONFLICT", "运行已更新，请重新打开后操作。");
  }

  const parsed = persistedRunSchema.parse({ ...next, revision: expectedRevision + 1 });
  await ensureSupabaseProject(
    parsed.project_id,
    parsed.request.project?.name ?? "ExcavaGuard project",
    Boolean(parsed.request.project?.name),
  );
  const { error } = await client.from("excavaguard_run_revisions").insert({
    run_id: parsed.run_id,
    revision: parsed.revision,
    project_id: parsed.project_id,
    record: parsed,
    created_at: parsed.updated_at,
  });
  if (error && isUniqueViolation(error)) {
    throw new AppError(409, "RUN_CONFLICT", "运行已更新，请重新打开后操作。");
  }
  if (error) throw supabaseStorageError("Supabase 运行记录保存失败", error);
  return parsed;
}

async function allSupabaseRuns(access: LocalAccess): Promise<PersistedRun[]> {
  const { client } = supabaseContext();
  const latestByRun = new Map<string, PersistedRun>();
  const pageSize = 1_000;
  for (let page = 0; page < 20 && latestByRun.size < 100; page += 1) {
    const from = page * pageSize;
    const { data, error } = await client
      .from("excavaguard_run_revisions")
      .select("run_id,revision,project_id,record,created_at")
      .eq("project_id", access.project_id)
      .order("created_at", { ascending: false })
      .range(from, from + pageSize - 1);
    if (error) throw supabaseStorageError("Supabase 运行历史读取失败", error);
    const rows = (data ?? []) as SupabaseRunRow[];
    for (const row of rows) {
      if (!latestByRun.has(row.run_id)) {
        const record = parseSupabaseRun(row);
        if (record.owner_id === access.owner_id) latestByRun.set(row.run_id, record);
      }
    }
    if (rows.length < pageSize) break;
  }
  return [...latestByRun.values()];
}

export async function readRun(runId: string, access: LocalAccess): Promise<PersistedRun> {
  if (getStorageProvider() === "supabase") {
    return readSupabaseRun(runId, access);
  }
  const latest = (await revisions(runId))[0];
  if (!latest) throw new AppError(404, "RUN_NOT_FOUND", "运行记录不存在。");
  let record: PersistedRun;
  try {
    record = persistedRunSchema.parse(JSON.parse(
      await readFile(/* turbopackIgnore: true */ join(runDirectory(runId), `${latest}.json`), "utf8"),
    ));
  } catch {
    throw new AppError(500, "STORAGE_ERROR", "运行记录已损坏或不可读取。");
  }
  if (record.run_id !== runId || record.revision !== latest) {
    throw new AppError(500, "STORAGE_ERROR", "运行记录版本不一致。");
  }
  if (record.project_id !== access.project_id || record.owner_id !== access.owner_id) {
    throw new AppError(404, "RUN_NOT_FOUND", "运行记录不存在。");
  }
  return record;
}

/** 追加修订；相同 expectedRevision 的并发写入只有一次可成功发布。 */
export async function saveRun(
  next: PersistedRun,
  expectedRevision: number,
  access: LocalAccess,
): Promise<PersistedRun> {
  if (next.project_id !== access.project_id || next.owner_id !== access.owner_id) {
    throw new AppError(403, "FORBIDDEN", "无权写入该项目。");
  }
  if (getStorageProvider() === "supabase") {
    return saveSupabaseRun(next, expectedRevision);
  }
  const latest = (await revisions(next.run_id))[0] ?? 0;
  if (latest !== expectedRevision) throw new AppError(409, "RUN_CONFLICT", "运行已更新，请重新打开后操作。");
  const parsed = persistedRunSchema.parse({ ...next, revision: expectedRevision + 1 });
  try {
    await atomicJson(join(runDirectory(next.run_id), `${parsed.revision}.json`), parsed, true);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      throw new AppError(409, "RUN_CONFLICT", "运行已更新，请重新打开后操作。");
    }
    throw new AppError(500, "STORAGE_ERROR", "运行记录保存失败，已保存的检查点仍保留。");
  }
  return parsed;
}

export async function listRuns(access: LocalAccess): Promise<RunSummary[]> {
  const records = await allRuns(access);
  return records.sort((left, right) => right.created_at.localeCompare(left.created_at))
    .slice(0, 100).map((record) => ({
      run_id: record.run_id,
      revision: record.revision,
      created_at: record.created_at,
      updated_at: record.updated_at,
      execution_status: record.execution_status,
      error: record.error,
      report_date: record.request.report_date,
      project_name: record.request.project?.name ?? "未提供工程名称",
      agent_status: record.result?.agent_run?.state.run.status ?? null,
      decision: record.review?.decision ?? null,
      parent_run_id: record.request.parent_run_id ?? null,
    }));
}

export async function allRuns(access: LocalAccess): Promise<PersistedRun[]> {
  if (getStorageProvider() === "supabase") {
    return allSupabaseRuns(access);
  }
  let entries: string[];
  try {
    entries = await readdir(/* turbopackIgnore: true */ root());
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw new AppError(500, "STORAGE_ERROR", "运行存储不可读取。");
  }
  const records: PersistedRun[] = [];
  for (const id of entries.filter((entry) => z.uuid().safeParse(entry).success)) {
    try {
      records.push(await readRun(id, access));
    } catch (error) {
      if (error instanceof AppError && error.code === "RUN_NOT_FOUND") continue;
      throw error;
    }
  }
  return records;
}

export async function readRunByDraftId(
  draftId: string,
  access: LocalAccess,
): Promise<PersistedRun | null> {
  if (!z.uuid().safeParse(draftId).success) {
    throw new AppError(400, "INVALID_REQUEST", "草稿标识不合法。");
  }
  if (getStorageProvider() === "local") {
    return (await allRuns(access)).find(
      (run) => run.result?.agent_run?.state.report_draft?.ref.artifact_id === draftId,
    ) ?? null;
  }
  const { client } = supabaseContext();
  const { data, error } = await client
    .from("excavaguard_report_artifacts")
    .select("run_id,project_id")
    .eq("draft_id", draftId)
    .limit(1)
    .maybeSingle();
  if (error) throw supabaseStorageError("Supabase 草稿归属读取失败", error);
  if (!data || data.project_id !== access.project_id) return null;
  return readRun(data.run_id, access);
}
