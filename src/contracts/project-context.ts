import { z } from "zod";
export const contextRecordSchema = z.strictObject({
  text: z.string().trim().min(1).max(12000),
  end_timestamp: z.string().max(60).optional(),
  source_location: z.string().max(300).optional(),
  method: z.string().max(100).optional(), soil: z.string().max(100).optional(), stage: z.string().max(100).optional(), groundwater: z.string().max(100).optional(),
  timestamp: z.string().max(60).optional().refine(v => !v || /^\d{4}-\d{2}-\d{2}(?:[T ](?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d{1,6})?)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)?)?$/.test(v) && z.iso.date().safeParse(v.slice(0,10)).success, "时间需包含有效日期"),
  section: z.string().trim().min(1).max(100).optional(),
  point_id: z.string().trim().min(1).max(100).optional(),
  recorder: z.string().trim().max(100).optional(),
  metric_keys: z.array(z.string().min(1).max(100)).max(30).default([]),
  assertion_key: z.string().trim().min(1).max(100).optional(),
  assertion_value: z.union([z.string().max(200), z.boolean(), z.number()]).optional(),
}).superRefine((r,c) => { if ((r.assertion_key !== undefined) !== (r.assertion_value !== undefined)) c.addIssue({code:"custom",message:"冲突核验字段需同时提供名称与值"}); });
export const contextUploadSchema = z.strictObject({
  kind: z.enum(["case", "work_condition", "patrol"]),
  title: z.string().trim().min(1).max(200),
  records: z.array(contextRecordSchema).min(1).max(200),
}).superRefine((d,c) => { if (d.kind !== "case" && d.records.some(r => !r.timestamp)) c.addIssue({code:"custom",message:"工况和巡视记录必须提供时间"}); });
export const contextDocumentSchema = contextUploadSchema.safeExtend({
  document_id: z.uuid(), project_id: z.uuid(), adapter_id: z.string(),
  sha256: z.string().regex(/^[a-f0-9]{64}$/), created_at: z.iso.datetime(),
  original_name: z.string().max(300).optional(), source_sha256: z.string().regex(/^[a-f0-9]{64}$/).optional(),
  uploaded_by: z.string().min(1), active: z.boolean().default(true),
});
export type ContextDocument = z.infer<typeof contextDocumentSchema>;
