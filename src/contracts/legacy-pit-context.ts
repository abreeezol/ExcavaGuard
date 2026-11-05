import { z } from "zod";
/** Compatibility only; new scene validation uses the adapter context.schema.json. */
export const projectContextSchema = z.strictObject({
  safety_level: z.enum(["一级", "二级", "三级"]),
  support_type: z.string().trim().min(1),
  excavation_depth_m: z.number().positive().max(200).nullable(),
  post_slab_from: z.iso.date().nullable().optional(),
  pipeline_type: z.string().trim().min(1).nullable().optional(),
  road_type: z.string().trim().min(1).nullable().optional(),
  design_values: z.record(z.string(), z.number()).optional(),
  danger_signals: z.record(z.string(), z.boolean()).optional(),
});

export type ProjectContextInput = z.infer<typeof projectContextSchema>;

