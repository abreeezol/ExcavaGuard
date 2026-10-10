import { randomUUID } from "node:crypto";
import { apiError, apiErrorFromException, apiOk } from "@/server/api/respond";
import { createRunRequestSchema } from "@/contracts/runs";
import { runJudgement } from "@/server/skills/evaluate-thresholds/runner";
import { getFile, localPathOf, standardDirOf } from "@/server/storage/monitoring-file-store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * 创建一次分析任务并同步返回结果。
 *
 * 链路：监测文件 → 阶段一 数据准备 → 阶段二 确定性计算 → 阶段三 规范比对
 *      → 日报接口载荷（`excavaguard.daily_report_input/v1`）
 *
 * 本层**不生成日报正文与版式文件**，只交付结构化载荷（见
 * `确定性计算层/04_日报模块接口契约.md`）。
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

    return apiOk({
      run_id: randomUUID(),
      created_at: new Date().toISOString(),
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
      },
      /** 阶段一的文件读取报告：编码、列映射、缺列情况。 */
      read_report: trace.read_report ?? null,
      summary,
      payload: envelope.result ?? null,
    });
  } catch (error) {
    return apiErrorFromException(error);
  }
}
