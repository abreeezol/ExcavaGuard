import { z } from "zod";

export const knownRiskLevelSchema = z.enum([
  "正常",
  "关注",
  "预警",
  "报警",
  "危险报警",
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
});

export const riskEvaluationTargetSchema = z.strictObject({
  risk_item_index: z.number().int().nonnegative(),
  point_id: z.string().trim().min(1).nullable(),
  metric_key: z.string().trim().min(1),
  metric_name: z.string().trim().min(1),
  timestamp: z.string().trim().min(1).nullable(),
  risk_level: knownRiskLevelSchema,
});

export const engineerRiskEvaluationSchema = riskEvaluationTargetSchema.extend({
  disposition: engineerEvaluationDispositionSchema,
  comment: engineerRiskEvaluationInputSchema.shape.comment,
});

export type EngineerEvaluationDisposition = z.infer<typeof engineerEvaluationDispositionSchema>;
export type EngineerRiskEvaluationInput = z.infer<typeof engineerRiskEvaluationInputSchema>;
export type EngineerRiskEvaluation = z.infer<typeof engineerRiskEvaluationSchema>;
export type RiskEvaluationTarget = z.infer<typeof riskEvaluationTargetSchema>;

/**
 * 工程师逐项评价只覆盖已形成确定性结论的非正常风险条目。
 * “未知”属于弃权队列，必须走数据补全/人工核查，不能在这里改写成已判定风险。
 */
export function riskEvaluationTargets(payload: unknown): RiskEvaluationTarget[] {
  if (!payload || typeof payload !== "object" || !("items" in payload)) return [];
  const items = (payload as { items?: unknown }).items;
  if (!Array.isArray(items)) return [];

  return items.flatMap((item, riskItemIndex) => {
    if (!item || typeof item !== "object") return [];
    const value = item as Record<string, unknown>;
    if (!["关注", "预警", "报警", "危险报警"].includes(String(value.risk_level))) return [];
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
