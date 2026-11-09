import { z } from "zod";

const paragraph = z.strictObject({
  text: z.string().trim().min(1).max(1800),
  evidence_ids: z.array(z.string().min(1).max(200)).max(12),
});

export const reportPlanSchema = z.strictObject({
  focus_indices: z.array(z.number().int().nonnegative()).min(1).max(200),
  investigations:z.array(z.strictObject({
    kind:z.enum(['cross_source_conflict','missing_context','recurring_warning','rule_applicability']),
    topic:z.string().trim().min(1).max(100),
    focus_indices:z.array(z.number().int().nonnegative()).min(1).max(20),
    fact_paths:z.array(z.string().min(1).max(300)).min(1).max(12),
    question:z.string().trim().min(1).max(600),
    rationale:z.string().trim().min(1).max(600),
  })).max(3).optional(),
  evidence_topics: z.array(z.string().min(1).max(100)).min(1).max(8),
});

export const reportNarrativeSchema = z.strictObject({
  feedback_responses: z.array(z.strictObject({
    feedback_id: z.string().min(1).max(100),
    status: z.enum(["addressed", "requires_human"]),
    response: paragraph,
  })).max(501).optional(),
  work_condition: paragraph,
  analysis: z.array(paragraph).min(1).max(8),
  recommendations: z.array(paragraph).min(1).max(8),
  limitations: z.array(paragraph).min(1).max(8),
  appendix_analysis: z.array(z.strictObject({
    form: z.string().trim().min(1).max(80),
    analysis: paragraph,
    recommendation: paragraph,
  })).max(32),
});

export const semanticAuditSchema = z.strictObject({
  issues: z.array(z.strictObject({
    code: z.string().min(1).max(100),
    responsibility: z.enum(["report-delivery", "supervisor", "human"]),
    path: z.string().min(1).max(300),
    message: z.string().min(1).max(1200),
  })).max(20),
});

export type ReportPlan = z.output<typeof reportPlanSchema>;
export type ReportNarrative = z.output<typeof reportNarrativeSchema>;
export type SemanticAudit = z.output<typeof semanticAuditSchema>;
export type ReportMode = "ai" | "template";
