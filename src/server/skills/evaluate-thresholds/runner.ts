import "server-only";
import type { StrictnessReport } from "@/contracts/monitoring-files";
import type { ProjectContextInput } from "@/contracts/runs";
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
  /** 由引擎侧读取文件（含编码探测与列名映射）。 */
  filePath?: string;
  context: ProjectContextInput;
  standardsDir?: string | null;
  reportDate?: string | null;
  project?: Record<string, unknown> | null;
  expectedIntervalDays?: number | null;
  valueRange?: [number | null, number | null] | null;
};

export async function runJudgement(request: JudgementRequest): Promise<SkillEnvelope> {
  const options: Record<string, unknown> = { with_payload: true };
  if (request.filePath) options.file_path = request.filePath;
  if (request.standardsDir) options.standards_dir = request.standardsDir;
  if (request.reportDate) options.report_date = request.reportDate;
  if (request.project) options.project = request.project;
  if (request.expectedIntervalDays != null) {
    options.expected_interval_days = request.expectedIntervalDays;
  }
  if (request.valueRange) options.value_range = request.valueRange;

  return callSkillScript("evaluate-thresholds", "run_judgement.py", {
    ...(request.records ? { records: request.records } : {}),
    context: request.context,
    options,
  });
}

export async function checkStandardStrictness(
  payload: Record<string, unknown>,
  context: Pick<ProjectContextInput, "safety_level" | "support_type" | "excavation_depth_m">,
): Promise<{ strictness: StrictnessReport; report: string; problems: string[] }> {
  const envelope = await callSkillScript("evaluate-thresholds", "check_strictness.py", {
    payload,
    context,
  });
  return {
    strictness: envelope.strictness as StrictnessReport,
    report: String(envelope.report ?? ""),
    problems: Array.isArray(envelope.problems) ? (envelope.problems as string[]) : [],
  };
}
