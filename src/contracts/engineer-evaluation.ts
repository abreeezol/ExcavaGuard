import { z } from "zod";

export const knownRiskLevelSchema = z.enum([
  "正常",
  "关注",
  "预警",
  "报警",
  "危险报警",
]);

export const riskLevelSchema = z.enum([
  ...knownRiskLevelSchema.options,
  "未知",
]);

export const engineerEvaluationDispositionSchema = z.enum([
  "confirmed",
  "follow_up_required",
  "disputed",
]);

export const engineerRiskEvaluationInputSchema = z.strictObject({
  risk_item_index: z.number().int().nonnegative(),
  disposition: engineerEvaluationDispositionSchema,
  comment: z.string().trim().min(1).max(1000),
  reviewed_risk_level: knownRiskLevelSchema.optional(),
});

export const riskEvaluationTargetSchema = z.strictObject({
  risk_item_index: z.number().int().nonnegative(),
  point_id: z.string().trim().min(1).nullable(),
  metric_key: z.string().trim().min(1),
  metric_name: z.string().trim().min(1),
  timestamp: z.string().trim().min(1).nullable(),
  risk_level: riskLevelSchema,
});

export const engineerRiskEvaluationSchema = riskEvaluationTargetSchema.extend({
  disposition: engineerEvaluationDispositionSchema,
  comment: engineerRiskEvaluationInputSchema.shape.comment,
  reviewed_risk_level: knownRiskLevelSchema.optional(),
});

export const effectiveRiskSummarySchema = z.strictObject({
  total: z.number().int().nonnegative(),
  overall_risk_level: riskLevelSchema,
  by_risk_level: z.strictObject({
    正常: z.number().int().nonnegative(),
    关注: z.number().int().nonnegative(),
    预警: z.number().int().nonnegative(),
    报警: z.number().int().nonnegative(),
    危险报警: z.number().int().nonnegative(),
    未知: z.number().int().nonnegative(),
  }),
  adjusted_count: z.number().int().nonnegative(),
});

export type EngineerEvaluationDisposition = z.infer<typeof engineerEvaluationDispositionSchema>;
export type EngineerRiskEvaluationInput = z.infer<typeof engineerRiskEvaluationInputSchema>;
export type EngineerRiskEvaluation = z.infer<typeof engineerRiskEvaluationSchema>;
export type RiskEvaluationTarget = z.infer<typeof riskEvaluationTargetSchema>;
export type KnownRiskLevel = z.infer<typeof knownRiskLevelSchema>;
export type RiskLevel = z.infer<typeof riskLevelSchema>;
export type EffectiveRiskSummary = z.infer<typeof effectiveRiskSummarySchema>;

const REVIEWABLE_RISK_LEVELS = new Set<RiskLevel>([
  "关注",
  "预警",
  "报警",
  "危险报警",
  "未知",
]);

/**
 * 可进入工程师复核的条目包含已知非正常风险和未知/弃权项。
 * 未知项仍是可选项，只有工程师明确给出最终等级后才形成评价。
 */
export function riskReviewTargets(payload: unknown): RiskEvaluationTarget[] {
  if (!payload || typeof payload !== "object" || !("items" in payload)) return [];
  const items = (payload as { items?: unknown }).items;
  if (!Array.isArray(items)) return [];

  return items.flatMap((item, riskItemIndex) => {
    if (!item || typeof item !== "object") return [];
    const value = item as Record<string, unknown>;
    const riskLevel = riskLevelSchema.safeParse(value.risk_level);
    if (!riskLevel.success || !REVIEWABLE_RISK_LEVELS.has(riskLevel.data)) return [];
    const target = riskEvaluationTargetSchema.safeParse({
      risk_item_index: riskItemIndex,
      point_id: typeof value.point_id === "string" && value.point_id.trim()
        ? value.point_id
        : null,
      metric_key: value.metric_key,
      metric_name: value.metric_name,
      timestamp: typeof value.timestamp === "string" && value.timestamp.trim()
        ? value.timestamp
        : null,
      risk_level: value.risk_level,
    });
    return target.success ? [target.data] : [];
  });
}

/** 接受草稿前必须逐项评价的已知非正常风险；未知项不计入门禁。 */
export function riskEvaluationTargets(payload: unknown): RiskEvaluationTarget[] {
  return riskReviewTargets(payload).filter(target => target.risk_level !== "未知");
}

export function effectiveRiskSummary(
  payload: unknown,
  evaluations: readonly EngineerRiskEvaluation[] = [],
): EffectiveRiskSummary {
  const counts: EffectiveRiskSummary["by_risk_level"] = {
    正常: 0,
    关注: 0,
    预警: 0,
    报警: 0,
    危险报警: 0,
    未知: 0,
  };
  const reviewedByIndex = new Map(
    evaluations
      .filter(evaluation => evaluation.reviewed_risk_level !== undefined)
      .map(evaluation => [evaluation.risk_item_index, evaluation.reviewed_risk_level!]),
  );
  const items = payload && typeof payload === "object" && "items" in payload
    ? (payload as { items?: unknown }).items
    : null;
  let adjustedCount = 0;

  if (Array.isArray(items)) {
    items.forEach((item, index) => {
      if (!item || typeof item !== "object") return;
      const original = riskLevelSchema.safeParse((item as Record<string, unknown>).risk_level);
      if (!original.success) return;
      const reviewed = reviewedByIndex.get(index);
      const effective = reviewed ?? original.data;
      counts[effective] += 1;
      if (reviewed !== undefined && reviewed !== original.data) adjustedCount += 1;
    });
  }

  const overall = ([
    "危险报警",
    "报警",
    "预警",
    "关注",
    "正常",
  ] as const).find(level => counts[level] > 0) ?? "未知";

  return effectiveRiskSummarySchema.parse({
    total: Object.values(counts).reduce((sum, count) => sum + count, 0),
    overall_risk_level: overall,
    by_risk_level: counts,
    adjusted_count: adjustedCount,
  });
}
