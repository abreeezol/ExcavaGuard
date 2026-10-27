import type { StandardEvidence } from "@/contracts/standard-evidence";
import type { StandardEvidenceSkillResult } from "@/server/skills/retrieve-standard-evidence/runner";

export const PERIOD_REVIEW_NOTICE = "仅核查现有知识库内的补充条文候选，不代表已核实全网最新规范或已确认工程适用性；新增要求须工程师复核，不自动修改风险判据。";

type Warning = { point_id: string; metric_key: string; metric_name: string; warning_days: number; warning_dates: string[] };
type Search = (request: { query: string; filters: { effective_status: "active" }; limit: number }) => Promise<StandardEvidenceSkillResult>;
const GROUPS: [string, string[]][] = [
  ["深层水平位移", ["深层", "测斜"]], ["内力与压力", ["内力", "土压力", "孔隙水"]],
  ["支撑与锚杆轴力", ["轴力", "锚杆"]], ["水位沉降与隆起", ["水位", "沉降", "地表竖向", "分层", "隆起"]],
  ["裂缝", ["裂缝"]], ["位移监测", ["位移", "墙顶", "顶部"]],
];

export async function reviewRecurringWarnings(payload: unknown, baselineIds: string[], search: Search) {
  const period = (payload as { period?: { recurring_warnings?: Warning[] } })?.period;
  const warnings = Array.isArray(period?.recurring_warnings)
    ? period.recurring_warnings.filter((w) => w.warning_days >= 2 && typeof w.metric_name === "string") : [];
  const groups = new Map<string, Warning[]>();
  for (const warning of warnings) {
    const group = GROUPS.find(([, words]) => words.some((word) => warning.metric_name.includes(word)))?.[0] ?? "位移监测";
    groups.set(group, [...(groups.get(group) ?? []), warning]);
  }
  const evidence = new Map<string, StandardEvidence>();
  const baseline = new Set(baselineIds);
  const gaps: string[] = [];
  const checks = [];
  for (const [group, entries] of groups) {
    const metrics = [...new Set(entries.map((w) => w.metric_name))];
    const request = {
      query: `${group} ${metrics.join("、")} 连续多日达到预警报警 监测频率加密 复测 现场复核 异常处置 应急措施 规范要求`.slice(0, 1000),
      // Deliberately remove the normal GB50497-only restriction, keep active-version gate.
      filters: { effective_status: "active" as const }, limit: 8,
    };
    const result = await search(request);
    if (result.status === "abstained" && result.code === "EVIDENCE_UNAVAILABLE") {
      throw new Error("EVIDENCE_UNAVAILABLE：多日预警追加规范核查失败，保留检查点，不宣称已完成核查。");
    }
    const accepted = result.status === "success" ? result.evidence.filter((item) =>
      item.metadata.effective_status === "active" && item.text.length <= 8000 &&
      /应|宜|不得|必须/.test(item.text) &&
      /监测频率|加密|复测|复核|预警|报警|险情|异常|应急|处置/.test(item.text) &&
      ([...metrics, ...GROUPS.find(([name]) => name === group)![1]].some((term) =>
        `${item.text} ${(item.metadata.applicability ?? []).join(" ")} ${item.metadata.monitoring_item ?? ""}`.includes(term)) ||
        // General excavation-monitoring response clauses can apply across metric groups.
        (/基坑/.test(`${item.text} ${(item.metadata.applicability ?? []).join(" ")}`) &&
          /监测频率|加密监测|监测报警|复测/.test(item.text))),
    ) : [];
    for (const item of accepted) evidence.set(item.id, item);
    const additional = accepted.filter((item) => !baseline.has(item.id)).map((item) => item.id);
    if (!accepted.length) gaps.push(`${group}存在多日预警，但未检索到足够相关的补充要求；需工程师扩大查证，不能认定无新增要求。`);
    if (result.status === "abstained" && result.code === "EVIDENCE_CONFLICT") gaps.push(`${group}规范候选存在效力/适用性冲突，须人工复核。`);
    checks.push({ group, metrics, points: [...new Set(entries.map((w) => w.point_id))],
      query: request.query, trace: result.trace, evidence_ids: accepted.map((item) => item.id),
      additional_evidence_ids: additional, status: additional.length ? "additional_candidates" : "no_additional_evidence",
      requires_human_review: true });
  }
  return { evidence: [...evidence.values()], gaps, review: {
    triggered: warnings.length > 0, threshold_days: 2, scope: "configured_knowledge_base_active_standards",
    notice: PERIOD_REVIEW_NOTICE, checks,
    status: !warnings.length ? "not_triggered" : checks.some((c) => c.additional_evidence_ids.length) ? "additional_candidates" : "no_additional_evidence",
  } };
}
