import "server-only";
import { loadEngineeringAdapter, adapterAssetPath, validateSceneParameters } from "@/server/engineering-adapters/registry";
import { dirname } from "node:path";
import type { StrictnessReport } from "@/contracts/monitoring-files";
import type { ReportPeriod } from "@/contracts/report-period";
import { callSkillScript, type SkillEnvelope } from "@/server/skills/python-bridge";

/**
 * evaluate-thresholds · 引擎调用
 *
 * 两个能力：
 *   1. `runJudgement` —— 三阶段确定性流程，产出日报接口载荷；
 *   2. `checkStandardStrictness` —— 校验用户阈值是否比默认规范更宽松。
 *
 * 两者都只是协议转换，判定与比较逻辑全在 `确定性计算层/pipeline/`。
 */

export type JudgementRequest = {
  /** 与 `filePath` 二选一。 */
  records?: unknown[];
  /** Server-side selection only; unsupported scenes fail closed. */
  adapterId?: string;
  /** 由引擎侧读取文件（含编码探测与列名映射）。 */
  filePath?: string;
  filePaths?: string[];
  context: Record<string, unknown>;
  standardsDir?: string | null;
  reportDate?: string | null;
  reportPeriod?: ReportPeriod;
  project?: Record<string, unknown> | null;
  expectedIntervalDays?: number | null;
  valueRange?: [number | null, number | null] | null;
};

export async function runJudgement(request: JudgementRequest): Promise<SkillEnvelope> {
  const { adapter, snapshot } = loadEngineeringAdapter(request.adapterId);
  const context = validateSceneParameters(adapter.id, request.context);
  const reportType = request.reportPeriod?.type ?? "daily";
  if (!adapter.supported_reports.includes(reportType)) throw new Error("ADAPTER_REPORT_UNSUPPORTED");
  const options: Record<string, unknown> = {
    with_payload: true,
    default_standards_dir: dirname(adapterAssetPath(adapter.assets.rules)),
    project: { ...request.project, professional_parameters: context, engineering_adapter: snapshot },
  };
  if (request.filePath) options.file_path = request.filePath;
  if (request.filePaths) options.file_paths = request.filePaths;
  if (request.standardsDir) options.standards_dir = request.standardsDir;
  if (request.reportDate) options.report_date = request.reportDate;
  if (request.reportPeriod) options.report_period = request.reportPeriod;
  if (request.expectedIntervalDays != null) {
    options.expected_interval_days = request.expectedIntervalDays;
  }
  if (request.valueRange) options.value_range = request.valueRange;

  const result = await callSkillScript("evaluate-thresholds", "run_judgement.py", {
    ...(request.records ? { records: request.records } : {}),
    context,
    options,
  }, { adapterId: adapter.id });
  return { ...result, trace: { ...result.trace, engineering_adapter: snapshot } };
}

export async function checkStandardStrictness(
  payload: Record<string, unknown>,
  context: Record<string, unknown>,
  adapterId?: string,
): Promise<{ strictness: StrictnessReport; report: string; problems: string[] }> {
  const envelope = await callSkillScript("evaluate-thresholds", "check_strictness.py", {
    payload,
    context,
  }, { adapterId });
  return {
    strictness: envelope.strictness as StrictnessReport,
    report: String(envelope.report ?? ""),
    problems: Array.isArray(envelope.problems) ? (envelope.problems as string[]) : [],
  };
}
