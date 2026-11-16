import { z } from "zod";

export const professionalReviewDecisionSchema = z.enum(["pass", "needs_changes"]);

export const professionalReviewCaseSchema = z.object({
  case_id: z.string().min(1),
  scenario: z.string().min(1),
  expected: z.string().min(1),
  evidence_reference: z.string().optional(),
});

export const professionalReviewEvaluationSchema = z.object({
  case_id: z.string().min(1),
  decision: professionalReviewDecisionSchema,
  comment: z.string(),
});

export const professionalReviewRecordSchema = z.object({
  revision: z.number().int().positive(),
  source_reference: z.string().optional(),
  evaluations: z.array(professionalReviewEvaluationSchema).optional(),
  status: z.string().optional(),
});

export const professionalReviewResponseSchema = z.object({
  suite: z.object({
    cases: z.array(professionalReviewCaseSchema).max(100),
  }),
  suite_hash: z.string().min(1),
  adapter_digest: z.string().min(1),
  status: z.string().min(1),
  review: professionalReviewRecordSchema.nullable().optional(),
});

export const professionalReviewSaveResponseSchema = z.object({
  review: professionalReviewRecordSchema.extend({
    status: z.string().min(1),
  }),
});

export type ProfessionalReviewData = z.infer<typeof professionalReviewResponseSchema>;
export type ProfessionalReviewDecision = z.infer<typeof professionalReviewDecisionSchema>;
