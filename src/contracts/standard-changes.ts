import { z } from "zod";

const text = z.string().trim().min(1);
export const proposedRuleSchema = z.strictObject({
  id: text.max(100), metric_key: text.max(100),
  kind: z.enum(["control", "recommended_range", "frequency", "other"]),
  field: z.enum(["cumulative", "rate"]), operator: z.enum([">=", ">"]),
  risk_level: z.enum(["关注", "预警", "报警", "危险报警"]),
  threshold: z.number().positive().finite(), unit: z.enum(["mm", "mm/d"]),
  // Positive, downward/inward cumulative displacement only. Other meanings remain review material.
  direction: z.literal("positive"),
  conditions: z.record(z.string(), z.union([text.max(200), z.number().finite(), z.boolean()])),
  point_ids: z.array(text.max(100)).max(100),
  source_chunk_id: text.max(200), quote: text.max(2600), clause: text.max(200),
  explanation: text.max(1500),
});
export const changeProposalSchema = z.strictObject({
  summary: text.max(3000), rules: z.array(proposedRuleSchema).max(40),
  unresolved: z.array(text.max(1000)).max(40),
});
export const changePlanSchema = z.strictObject({ focus: z.array(text.max(500)).max(12), cautions: z.array(text.max(500)).max(12) });
export const changeAuditSchema = z.strictObject({ issues: z.array(z.strictObject({
  rule_id: text.max(100), message: text.max(1500),
})).max(50) });
export type ProposedRule = z.infer<typeof proposedRuleSchema>;
export type ChangeProposal = z.infer<typeof changeProposalSchema>;
export type ChangeAudit = z.infer<typeof changeAuditSchema>;
export const changeDecisionSchema = z.strictObject({
  rule_id: text.max(100), action: z.enum(["accept", "reject"]),
  note: z.string().trim().max(1500), edited: proposedRuleSchema.optional(),
});
export type ChangeDecision = z.infer<typeof changeDecisionSchema>;
export type StandardChange = {
  id: string; document_id: string; document_sha256: string; standard_name: string; standard_version: string;
  adapter_id: string; adapter_digest: string; configuration_hash: string;
  status: "pending" | "returned" | "published" | "rejected" | "disabled";
  revision_round: number; created_at: string; actor: string;
  proposal: ChangeProposal; audit: ChangeAudit; validation: Record<string, string[]>;
  source_pages: Record<string, number>;
  trace: { role: "supervisor" | "report-delivery" | "audit"; model: string }[];
  feedback: { text: string; actor: string; at: string }[];
  decisions: ChangeDecision[];
};
export type StandardChangeState = { version: number; project_id: string; changes: StandardChange[]; updated_at: string; updated_by: string };
