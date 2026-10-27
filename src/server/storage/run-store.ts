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

type SupabaseRunSummaryRow = {
  run_id: string;
  revision: number;
  project_id: string;
  row_created_at: string;
  owner_id: string | null;
  record_created_at: string | null;
  record_updated_at: string | null;
  execution_status: string | null;
  error: unknown;
  report_date: string | null;
  project_name: string | null;
  agent_status: string | null;
  decision: string | null;
  parent_run_id: string | null;
};

const runExecutionStatusSchema = persistedRunSchema.shape.execution_status;
const runErrorSchema = persistedRunSchema.shape.error;
const reviewDecisionSchema = z.enum(["accepted", "needs_changes", "rejected"]);
const RUN_HISTORY_LIMIT = 100;
const RUN_HISTORY_PAGE_SIZE = 200;
const RUN_HISTORY_MAX_PAGES = 40;

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
  if (!access.role && record.owner_id !== access.owner_id) {
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
        if (access.role || record.owner_id === access.owner_id) latestByRun.set(row.run_id, record);
      }
    }
    if (rows.length < pageSize) break;
  }
  return [...latestByRun.values()];
}

function supabaseSummary(row: SupabaseRunSummaryRow, access: LocalAccess): RunSummary | null {
  if (row.project_id !== access.project_id) return null;
  if (!access.role && row.owner_id !== access.owner_id) return null;
  const executionStatus = runExecutionStatusSchema.safeParse(row.execution_status);
  const error = runErrorSchema.safeParse(row.error);
  let decision: z.infer<typeof reviewDecisionSchema> | null = null;
  if (row.decision !== null) {
    const parsedDecision = reviewDecisionSchema.safeParse(row.decision);
    if (!parsedDecision.success) {
      throw new AppError(500, "STORAGE_ERROR", "Supabase 运行历史摘要字段不合法。");
    }
    decision = parsedDecision.data;
  }
  if (!executionStatus.success || !error.success) {
    throw new AppError(500, "STORAGE_ERROR", "Supabase 运行历史摘要字段不合法。");
  }
  return {
    run_id: row.run_id,
    revision: row.revision,
    created_at: row.record_created_at ?? row.row_created_at,
    updated_at: row.record_updated_at ?? row.row_created_at,
    execution_status: executionStatus.data,
    error: error.data,
    report_date: row.report_date ?? "",
    project_name: row.project_name?.trim() || "未提供工程名称",
    agent_status: row.agent_status,
    decision,
    parent_run_id: row.parent_run_id,
  };
}

async function listSupabaseRuns(access: LocalAccess): Promise<RunSummary[]> {
  const { client } = supabaseContext();
  const latestByRun = new Map<string, RunSummary>();
  for (
    let page = 0;
    page < RUN_HISTORY_MAX_PAGES && latestByRun.size < RUN_HISTORY_LIMIT;
    page += 1
  ) {
    const from = page * RUN_HISTORY_PAGE_SIZE;
    const { data, error } = await client
      .from("excavaguard_run_revisions")
      .select(`
        run_id,
        revision,
        project_id,
        row_created_at:created_at,
        owner_id:record->>owner_id,
        record_created_at:record->>created_at,
        record_updated_at:record->>updated_at,
        execution_status:record->>execution_status,
        error:record->error,
        report_date:record->request->>report_date,
        project_name:record->request->project->>name,
        agent_status:record->result->agent_run->state->run->>status,
        decision:record->review->>decision,
        parent_run_id:record->request->>parent_run_id
      `)
      .eq("project_id", access.project_id)
      .order("created_at", { ascending: false })
      .range(from, from + RUN_HISTORY_PAGE_SIZE - 1);
    if (error) throw supabaseStorageError("Supabase 运行历史读取失败", error);
    const rows = (data ?? []) as SupabaseRunSummaryRow[];
    for (const row of rows) {
      if (latestByRun.has(row.run_id)) continue;
      const summary = supabaseSummary(row, access);
      if (summary) latestByRun.set(row.run_id, summary);
    }
    if (rows.length < RUN_HISTORY_PAGE_SIZE) break;
  }
  return [...latestByRun.values()]
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .slice(0, RUN_HISTORY_LIMIT);
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
  if (record.project_id !== access.project_id || (!access.role && record.owner_id !== access.owner_id)) {
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
  if (next.project_id !== access.project_id || (!access.role && next.owner_id !== access.owner_id) ||
      (expectedRevision === 0 && next.owner_id !== access.owner_id)) {
    throw new AppError(403, "FORBIDDEN", "无权写入该项目。");
  }
  if (expectedRevision > 0) {
    const previous = await readRun(next.run_id, access);
    if (previous.owner_id !== next.owner_id) throw new AppError(403, "FORBIDDEN", "不可更改运行创建者。");
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
  if (getStorageProvider() === "supabase") {
    return listSupabaseRuns(access);
  }
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
      ...(record.request.report_period ? { report_period: record.request.report_period } : {}),
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
