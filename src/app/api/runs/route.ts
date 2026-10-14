import { randomUUID } from "node:crypto";
import { apiError, apiErrorFromException, apiOk } from "@/server/api/respond";
import { createRunRequestSchema } from "@/contracts/runs";
import { executeAgentRun } from "@/server/agents/executor";
import { runJudgement } from "@/server/skills/evaluate-thresholds/runner";
import { getFile, localPathOf, standardDirOf } from "@/server/storage/monitoring-file-store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * 创建一次分析任务并同步返回结果。
 *
 * 链路：监测文件 → 阶段一 数据准备 → 阶段二 确定性计算 → 阶段三 规范比对
 *      → 日报接口载荷（`excavaguard.daily_report_input/v1`）
 *      →（仅 `options.generate_report=true`）报告交付 → 独立审计 → 人工复核
 *
 * 默认只交付确定性结构化载荷；报告链必须由调用方显式开启。确定性计算层本身仍不
 * 生成日报正文与版式文件，报告由独立 Skill/Agent 消费冻结载荷生成。
 *
 * 运行记录**尚未持久化**：`run_id` 仅用于本次请求的追溯，
 * 不写入数据库，也不做鉴权与项目归属校验（工程化前必须补齐）。
 */
export async function POST(request: Request) {
  const mediaType = request.headers.get("content-type")?.split(";")[0].trim().toLowerCase();
  if (mediaType !== "application/json") {
    return apiError(415, "UNSUPPORTED_MEDIA_TYPE", "请使用 application/json。");
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return apiError(400, "INVALID_JSON", "请求正文不是有效 JSON。");
  }

  const parsed = createRunRequestSchema.safeParse(body);
  if (!parsed.success) {
    return apiError(400, "INVALID_REQUEST", "请检查监测文件标识、报告日期与工程条件。", {
      fields: [...new Set(parsed.error.issues.map((issue) => issue.path.join(".")))],
    });
  }
  const input = parsed.data;

  const monitoring = await getFile(input.monitoring_file_id);
  if (!monitoring || monitoring.kind !== "monitoring") {
    return apiError(404, "FILE_NOT_FOUND", "未找到该监测数据文件，请先上传。");
  }
  const filePath = await localPathOf(input.monitoring_file_id);
  if (!filePath) {
    return apiError(404, "FILE_NOT_FOUND", "监测文件已不在存储中，请重新上传。");
  }

  let standardsDir: string | null = null;
  if (input.standards_file_id) {
    const standard = await getFile(input.standards_file_id);
    if (!standard || standard.kind !== "standard") {
      return apiError(404, "FILE_NOT_FOUND", "未找到该用户规范文件，请先上传。");
    }
    standardsDir = await standardDirOf(input.standards_file_id);
    if (!standardsDir) {
      return apiError(404, "FILE_NOT_FOUND", "用户规范文件已不在存储中，请重新上传。");
    }
  }

  try {
    const runId = randomUUID();
    const createdAt = new Date().toISOString();
    const envelope = await runJudgement({
      filePath,
      context: input.context,
      standardsDir,
      reportDate: input.report_date,
      project: (input.project as Record<string, unknown> | undefined) ?? null,
      expectedIntervalDays: input.options?.expected_interval_days ?? null,
      valueRange: input.options?.value_range ?? null,
    });

    const trace = (envelope.trace ?? {}) as Record<string, unknown>;
    const summary = (envelope.summary ?? {}) as Record<string, unknown>;
    const payload = envelope.result ?? null;
    const execution = input.options?.generate_report
      ? await executeAgentRun({
          enginePayload: payload,
          runId,
          createdAt: new Date().toISOString(),
        })
      : null;
    const reportDraft = execution?.state.report_draft;
    const downloads =
      reportDraft && execution?.state.audit_result?.valid === true
      ? reportDraft.artifacts.map((artifact) => ({
          kind: artifact.kind,
          file_name: artifact.file_name,
          sha256: artifact.sha256,
          size_bytes: artifact.size_bytes,
          url:
            `/api/report-artifacts/${reportDraft.ref.artifact_id}/` +
            encodeURIComponent(artifact.file_name),
        }))
      : [];

    return apiOk({
      run_id: runId,
      created_at: createdAt,
      project_id: input.project_id,
      monitoring_file_id: input.monitoring_file_id,
      standards_file_id: input.standards_file_id ?? null,
      effective_standard_origin:
        typeof summary.effective_standard_origin === "string"
          ? summary.effective_standard_origin
          : null,
      engine: {
        elapsed_ms: Number(trace.elapsed_ms ?? 0),
        python: typeof trace.python === "string" ? trace.python : undefined,
        records: Number(trace.records ?? 0),
        source_records: Number(trace.source_records ?? trace.records ?? 0),
        daily_aggregation: trace.daily_aggregation ?? null,
      },
      /** 阶段一的文件读取报告：编码、列映射、缺列情况。 */
      read_report: trace.read_report ?? null,
      summary,
      payload,
      agent_run: execution
        ? {
            state: execution.state,
            terminal_action: execution.terminalAction,
            steps: execution.steps,
            downloads,
          }
        : null,
    });
  } catch (error) {
    return apiErrorFromException(error);
  }
}
