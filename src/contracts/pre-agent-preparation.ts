import { z } from "zod";
export const preparationSummarySchema=z.strictObject({
  schema:z.literal('excavaguard.pre_agent_preparation/v1'),
  scene:z.strictObject({
    engineering_name:z.string(),adapter_id:z.string(),adapter_version:z.string(),adapter_digest:z.string(),
    settings_source:z.enum(['project','request']),
    public_standards:z.array(z.strictObject({name:z.string(),version:z.string(),status:z.string(),applicable:z.boolean()})),
    project_standards:z.number().int().nonnegative(),supplemental_rules:z.number().int().nonnegative(),rule_version:z.number().int().nonnegative(),
  }),
  facts:z.strictObject({
    report_kind:z.string(),start_date:z.string(),end_date:z.string(),observations:z.number().int().nonnegative(),
    channels:z.number().int().nonnegative(),unknown:z.number().int().nonnegative(),pending:z.number().int().nonnegative(),
    adopted_criteria:z.array(z.strictObject({name:z.string(),clause:z.string(),rule_id:z.string().nullable()})),
    gaps:z.array(z.string()),
  }),
  sources:z.array(z.strictObject({file_id:z.string(),name:z.string(),sha256:z.string()})),
  fact_digest:z.string().regex(/^[a-f0-9]{64}$/),
});
export type PreparationSummary=z.infer<typeof preparationSummarySchema>;
