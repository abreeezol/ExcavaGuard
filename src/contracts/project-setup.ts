import { z } from "zod";

export const engineeringSetupFieldSchema = z.strictObject({
  key: z.string().min(1),
  label: z.string().min(1),
  required: z.boolean(),
  source: z.literal("engineer_confirmed"),
  choices: z.array(z.string()).optional(),
  choice_labels: z.record(z.string(), z.string()).optional(),
  input_type: z.enum(["text", "number", "date", "checkbox"]).optional(),
  missing_policy: z.string().optional(),
});

export const engineeringSetupSchema = z.strictObject({
  id: z.enum(["foundation_pit", "tunnel"]),
  name: z.string().min(1),
  adapter_version: z.string().min(1),
  supported_reports: z.array(z.enum(["daily", "weekly", "monthly", "custom"])).min(1),
  core_fields: z.array(engineeringSetupFieldSchema).min(1),
});

export const engineeringSetupsSchema = z.array(engineeringSetupSchema).min(1);

export type EngineeringSetupField = z.infer<typeof engineeringSetupFieldSchema>;
export type EngineeringSetup = z.infer<typeof engineeringSetupSchema>;
