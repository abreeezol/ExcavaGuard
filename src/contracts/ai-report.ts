import { z } from "zod";

const paragraph = z.strictObject({
  text: z.string().trim().min(1).max(1800),
  evidence_ids: z.array(z.string().min(1).max(200)).max(12),
});

export const reportPlanSchema = z.strictObject({
  focus_indices: z.array(z.number().int().nonnegative()).min(1).max(200),
  evidence_topics: z.array(z.string().min(1).max(100)).min(1).max(8),
});

export const reportNarrativeSchema = z.strictObject({
  work_condition: paragraph,
  analysis: z.array(paragraph).min(1).max(8),
  recommendations: z.array(paragraph).min(1).max(8),
  limitations: z.array(paragraph).min(1).max(8),
  appendix_analysis: z.array(z.strictObject({
    form: z.enum(["A", "B", "C", "D", "E", "F"]),
    analysis: paragraph,
    recommendation: paragraph,
  })).max(6),
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
