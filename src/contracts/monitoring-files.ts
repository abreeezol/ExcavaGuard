import { z } from "zod";

/**
 * 上传文件与读取报告的共享契约。
 *
 * 注意：`storedFileSchema` 只描述**元数据**，不含文件内容；
 * 文件本体由服务端存储层保管，客户端只能通过 `file_id` 引用。
 */

export const fileKindSchema = z.enum(["monitoring", "standard"]);
export type FileKind = z.infer<typeof fileKindSchema>;

export const storedFileSchema = z.strictObject({
  file_id: z.uuid(),
  kind: fileKindSchema,
  original_name: z.string().trim().min(1),
  size_bytes: z.number().int().nonnegative(),
  media_type: z.string().trim().min(1),
  /** 内容指纹，用于确认「分析用的就是上传的那份」。 */
  sha256: z.string().regex(/^[0-9a-f]{64}$/),
  created_at: z.iso.datetime(),
  /** 当前仅实现 local；supabase 为生产路径，见存储层说明。 */
  storage: z.enum(["local", "supabase"]),
});

export type StoredFile = z.infer<typeof storedFileSchema>;

/** 阶段一读取器报告（`file_reader.read_monitoring_file` 的 report）。 */
export const readReportSchema = z.looseObject({
  source: z.string().optional(),
  format: z.string().optional(),
  encoding: z.string().nullable().optional(),
  delimiter: z.string().nullable().optional(),
  sheet: z.string().optional(),
  raw_rows: z.number().optional(),
  header: z.array(z.string()).optional(),
  /** 列下标（字符串化）→ 规范字段名 */
  mapped_columns: z.record(z.string(), z.string()).optional(),
  unmapped_columns: z.array(z.string()).optional(),
  missing_required: z.array(z.string()).optional(),
  derivable_columns_present: z.array(z.string()).optional(),
  data_rows: z.number().optional(),
  ok: z.boolean().optional(),
  errors: z.array(z.string()).optional(),
});

export type ReadReport = z.infer<typeof readReportSchema>;

/** `POST /api/monitoring-files` 成功响应。 */
export const uploadMonitoringFileResponseSchema = z.strictObject({
  file: storedFileSchema,
  read_report: readReportSchema.nullable(),
});

/** `GET /api/monitoring-files` 成功响应。 */
export const listFilesResponseSchema = z.strictObject({
  files: z.array(storedFileSchema),
});

/**
 * 用户规范上传请求体。
 *
 * 结构校验以 Python 侧 `StandardsRegistry.validate_upload()` 为准
 * （它同时校验 rule_id 唯一性、字段类型与条件取值），
 * 这里只做最低限度把关，避免两处规则漂移。
 */
export const userStandardPayloadSchema = z.looseObject({
  schema_version: z.string().optional(),
  source_id: z.string().trim().min(1),
  source_label: z.string().trim().min(1),
  source_type: z.string().optional(),
  metrics: z
    .record(z.string(), z.unknown())
    .refine((metrics) => Object.keys(metrics).length > 0, {
      message: "metrics 不能为空。",
    }),
});

export type UserStandardPayload = z.infer<typeof userStandardPayloadSchema>;

/** 单条阈值差异（与 Python `limit_strictness` 输出一致）。 */
export const strictnessDiffSchema = z.looseObject({
  metric_key: z.string(),
  metric_name: z.string(),
  field: z.string(),
  field_display: z.string(),
  unit: z.string().optional(),
  user_value: z.number().nullable().optional(),
  default_value: z.number().nullable().optional(),
  direction: z.enum(["looser", "stricter", "equal", "incomparable"]),
  default_basis: z.string().optional(),
  default_evidence: z.looseObject({
    standard: z.string().optional(),
    clause: z.string().optional(),
    note: z.string().optional(),
  }),
  user_evidence: z.looseObject({
    standard: z.string().optional(),
    clause: z.string().optional(),
  }),
  user_rule_id: z.string().nullable().optional(),
  delta_pct: z.number().optional(),
  severity: z.string().optional(),
  note: z.string().optional(),
});

export type StrictnessDiff = z.infer<typeof strictnessDiffSchema>;

export const strictnessReportSchema = z.looseObject({
  checked: z.number(),
  looser_count: z.number(),
  incomparable_count: z.number(),
  has_looser: z.boolean(),
  severity_counts: z.record(z.string(), z.number()),
  looser: z.array(strictnessDiffSchema),
  incomparable: z.array(strictnessDiffSchema),
  unmatched: z
    .array(
      z.looseObject({
        metric_key: z.string(),
        metric_name: z.string(),
        rule_id: z.string().nullable().optional(),
        reason: z.string(),
      }),
    )
    .optional(),
});

export type StrictnessReport = z.infer<typeof strictnessReportSchema>;

/** `POST /api/standards` 成功响应。 */
export const uploadStandardResponseSchema = z.strictObject({
  file: storedFileSchema,
  strictness: strictnessReportSchema,
  /** 可直接展示给用户的文本报告；无更宽松项时为空串。 */
  report: z.string(),
});
