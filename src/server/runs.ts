import "server-only";
import { randomUUID } from "node:crypto";
import { dirname } from "node:path";
import { agentRunStateSchema } from "@/contracts/agent-runtime";
import type { LocalAccess } from "@/contracts/access";
import type { CreateRunRequest, PersistedRun, ReviewRequest, RunResult } from "@/contracts/runs";
import { AppError } from "@/server/api/errors";
import { executeAgentRun, type AgentRunExecutionResult } from "@/server/agents/executor";
import { runJudgement } from "@/server/skills/evaluate-thresholds/runner";
import {
  getFile,
  materializeStoredFile,
  type MaterializedFile,
} from "@/server/storage/monitoring-file-store";
import { readRun, saveRun } from "@/server/storage/run-store";
import {
  persistReportFiles,
  verifyReportFiles,
} from "@/server/storage/report-files";
import { EngineError } from "@/server/skills/python-bridge";

const LEASE_MS = 180_000;

function agentResult(
  execution: AgentRunExecutionResult,
  includeDownloads = true,
): NonNullable<RunResult["agent_run"]> {
  const draft = execution.state.report_draft;
  const decision = execution.state.human_review.decision;
  const downloads = includeDownloads && draft && execution.state.audit_result?.valid &&
    decision !== "needs_changes" && decision !== "rejected"
    ? draft.artifacts.map((artifact) => ({
      kind: artifact.kind,
      file_name: artifact.file_name,
      sha256: artifact.sha256,
      size_bytes: artifact.size_bytes,
      url: `/api/report-artifacts/${draft.ref.artifact_id}/${encodeURIComponent(artifact.file_name)}`,
    })) : [];
  return {
    state: execution.state,
    terminal_action: execution.terminalAction,
    steps: execution.steps,
    downloads,
  };
}

export function runView(record: PersistedRun) {
  return { ...record.result, run_id: record.run_id, record };
}

async function requireFile(fileId: string, kind: "monitoring" | "standard", access: LocalAccess) {
  const file = await getFile(fileId);
  if (!file || file.kind !== kind || file.project_id !== access.project_id) {
    throw new AppError(404, "FILE_NOT_FOUND", "未找到该项目的上传文件，请先上传。");
  }
}

async function materializeRequiredFile(fileId: string): Promise<MaterializedFile> {
  const materialized = await materializeStoredFile(fileId);
  if (!materialized) {
    throw new AppError(404, "FILE_NOT_FOUND", "上传文件已不在存储中，请重新上传。");
  }
  return materialized;
}

async function executeSaved(record: PersistedRun, access: LocalAccess, resume = false) {
  let current = record;
  try {
    if (!current.result) throw new AppError(409, "INVALID_TRANSITION", "尚无冻结计算结果，请重新创建运行。");
    const result = current.result;
    const execution = await executeAgentRun({
      enginePayload: result.payload,
      runId: current.run_id,
      reportMode: current.request.options?.report_mode ?? "ai",
      initialState: resume ? result.agent_run?.state : undefined,
    }, {
      checkpoint: async (checkpoint) => {
        current = await saveRun({
          ...current,
          result: { ...result, agent_run: agentResult(checkpoint, false) },
          updated_at: new Date().toISOString(),
        }, current.revision, access);
      },
    });
    if (execution.state.report_draft && execution.state.audit_result?.valid) {
      await persistReportFiles(
        current.run_id,
        current.project_id,
        execution.state.report_draft,
      );
    }
    current = await saveRun({
      ...current,
      result: { ...result, agent_run: agentResult(execution) },
      execution_status: execution.terminalAction.type === "wait_for_capability" ? "waiting" : "completed",
      lease_until: null,
      updated_at: new Date().toISOString(),
    }, current.revision, access);
    return current;
  } catch (error) {
    await saveFailure(current, access, error);
    throw error;
  }
}

async function saveFailure(record: PersistedRun, access: LocalAccess, error: unknown) {
  if (error instanceof AppError && error.code === "RUN_CONFLICT") return;
  await saveRun({
    ...record,
    execution_status: "failed",
    lease_until: null,
    updated_at: new Date().toISOString(),
    error: {
      code: error instanceof AppError ? error.code
        : error instanceof EngineError ? error.engineCode : "EXECUTION_FAILED",
      message: error instanceof Error ? error.message : "执行失败。",
    },
  }, record.revision, access);
}

export async function createRun(input: CreateRunRequest, access: LocalAccess): Promise<PersistedRun> {
  await requireFile(input.monitoring_file_id, "monitoring", access);
  if (input.standards_file_id) {
    await requireFile(input.standards_file_id, "standard", access);
  }
  if (input.parent_run_id) await readRun(input.parent_run_id, access);
  const at = new Date().toISOString();
  let current = await saveRun({
    schema: "excavaguard.persisted_run/v1",
    run_id: randomUUID(),
    revision: 1,
    owner_id: access.owner_id,
    project_id: access.project_id,
    created_at: at,
    updated_at: at,
    execution_status: "running",
    lease_until: new Date(Date.now() + LEASE_MS).toISOString(),
    request: input,
    result: null,
    error: null,
    review: null,
  }, 0, access);
  let monitoringFile: MaterializedFile | null = null;
  let standardFile: MaterializedFile | null = null;
  let primaryError: unknown = null;
  try {
    monitoringFile = await materializeRequiredFile(input.monitoring_file_id);
    standardFile = input.standards_file_id
      ? await materializeRequiredFile(input.standards_file_id)
      : null;
    const envelope = await runJudgement({
      filePath: monitoringFile.path,
      standardsDir: standardFile ? dirname(standardFile.path) : null,
      context: input.context,
      reportDate: input.report_date,
      project: input.project ?? null,
      expectedIntervalDays: input.options?.expected_interval_days ?? null,
      valueRange: input.options?.value_range ?? null,
    });
    const trace = (envelope.trace ?? {}) as Record<string, unknown>;
    const summary = (envelope.summary ?? {}) as Record<string, unknown>;
    current = await saveRun({
      ...current,
      result: {
        run_id: current.run_id, created_at: at, project_id: input.project_id,
        monitoring_file_id: input.monitoring_file_id,
        standards_file_id: input.standards_file_id ?? null,
        effective_standard_origin: typeof summary.effective_standard_origin === "string" ? summary.effective_standard_origin : null,
        engine: {
          elapsed_ms: Number(trace.elapsed_ms ?? 0),
          python: typeof trace.python === "string" ? trace.python : undefined,
          records: Number(trace.records ?? 0),
          source_records: Number(trace.source_records ?? trace.records ?? 0),
          daily_aggregation: trace.daily_aggregation ?? null,
        },
        read_report: trace.read_report ?? null, summary, payload: envelope.result ?? null,
        agent_run: null,
      },
      updated_at: new Date().toISOString(),
      execution_status: input.options?.generate_report ? "running" : "completed",
      lease_until: input.options?.generate_report ? new Date(Date.now() + LEASE_MS).toISOString() : null,
    }, current.revision, access);
  } catch (error) {
    primaryError = error;
    await saveFailure(current, access, error);
    throw error;
  } finally {
    const cleanups = [monitoringFile, standardFile]
      .filter((file): file is MaterializedFile => file !== null)
      .map((file) => file.cleanup());
    const cleanupResults = await Promise.allSettled(cleanups);
    const cleanupFailure = cleanupResults.find((result) => result.status === "rejected");
    if (cleanupFailure?.status === "rejected" && primaryError === null) {
      const error = new AppError(500, "STORAGE_ERROR", "Supabase 临时文件清理失败，停止运行。");
      await saveFailure(current, access, error);
      throw error;
    }
  }
  return input.options?.generate_report ? executeSaved(current, access) : current;
}

export async function reviewRun(runId: string, input: ReviewRequest, access: LocalAccess) {
  const record = await readRun(runId, access);
  if (record.revision !== input.expected_revision) throw new AppError(409, "RUN_CONFLICT", "运行已更新，请重新打开后复核。");
  const agent = record.result?.agent_run;
  const draft = agent?.state.report_draft;
  if (record.execution_status !== "completed" || !agent || !draft ||
      agent.state.run.status !== "awaiting_human_review" || !agent.state.audit_result?.valid ||
      record.review || agent.state.human_review.decision !== null) {
    throw new AppError(409, "INVALID_TRANSITION", "仅可复核尚未提交决定且已通过审计的当前草稿。");
  }
  if (JSON.stringify(draft.ref) !== JSON.stringify(input.draft_ref)) {
    throw new AppError(409, "RUN_CONFLICT", "草稿版本已变化，请重新打开后复核。");
  }
  if (input.decision === "accepted") await verifyReportFiles(draft);
  const at = new Date().toISOString();
  const state = agentRunStateSchema.parse({
    ...agent.state,
    run: {
      ...agent.state.run, updated_at: at,
      status: input.decision === "accepted" ? "awaiting_human_review" : "stopped",
      current_stage: input.decision === "accepted" ? "human_review" : "stopped",
    },
    human_review: {
      ...agent.state.human_review, submitted_at: at, decision: input.decision,
      reasons: [...agent.state.human_review.reasons, input.reason],
    },
    trace: [...agent.state.trace, {
      event_id: randomUUID(), agent: "supervisor", capability: "human-review",
      status: "success", input_versions: { draft: `${draft.ref.artifact_id}@${draft.ref.version}:${draft.ref.content_hash}` },
      output_versions: { decision: input.decision }, rule_ids: [], evidence_ids: [],
      error: null, return_reason: input.reason, started_at: at, finished_at: at,
    }],
  });
  return saveRun({
    ...record, updated_at: at,
    result: { ...record.result!, agent_run: agentResult({
      state,
      terminalAction: {
        type: "handoff_to_human", agent: "supervisor",
        reason_code: input.decision === "accepted" ? "AUDIT_PASSED" : "RUN_STOPPED",
        details: input.decision === "accepted"
          ? "已记录工程师接受当前草稿的决定，正式审核与签发仍需人工完成。"
          : "已记录工程师退回或拒绝的决定，停止自动处理，修正输入后可新建关联运行。",
      },
      steps: agent.steps,
    }) },
    review: {
      decision: input.decision, reason: input.reason,
      submitted_at: at, owner_id: access.owner_id, draft_ref: draft.ref,
    },
  }, record.revision, access);
}

export async function resumeRun(runId: string, revision: number, access: LocalAccess) {
  const record = await readRun(runId, access);
  if (record.revision !== revision) throw new AppError(409, "RUN_CONFLICT", "运行已更新，请重新打开。");
  const state = record.result?.agent_run?.state;
  if (record.execution_status === "completed" || record.review || !state ||
      (record.lease_until && Date.parse(record.lease_until) > Date.now()) ||
      Date.parse(state.limits.deadline_at) <= Date.now()) {
    throw new AppError(409, "INVALID_TRANSITION", "当前运行不可续跑。活动任务请等待；预算到期或无检查点时请加载输入新建运行。");
  }
  const claimed = await saveRun({
    ...record, execution_status: "running", error: null,
    updated_at: new Date().toISOString(),
    lease_until: new Date(Date.now() + LEASE_MS).toISOString(),
  }, record.revision, access);
  return executeSaved(claimed, access, true);
}
