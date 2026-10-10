import { z } from "zod";

/**
 * 分析任务（run）的请求与响应契约。
 *
 * 数据流：
 *   上传监测文件 → `monitoring_file_id`
 *   （可选）上传用户规范 → `standards_file_id`
 *   提供工程条件 → `context`
 *   → 确定性计算层（阶段一 数据准备 → 阶段二 确定性计算 → 阶段三 规范比对）
 *   → 日报接口载荷 `excavaguard.daily_report_input/v1`
 */

/**
 * 工程条件。**必须由调用方显式给出**，引擎不做任何默认假设。
 *
 * `excavation_depth_m` 允许为 `null`，表示"暂未提供"：
 * 此时含 `%H` 的累计值判据无法换算，引擎会**弃权**而不是退回绝对量限值
 * （见 `AGENTS.md` 工程安全边界与 `06_..._目标实现度评估.md` P1-2）。
 */
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

export const createRunRequestSchema = z.strictObject({
  project_id: z.uuid(),
  monitoring_file_id: z.uuid(),
  report_date: z.iso.date(),
  context: projectContextSchema,
  /** 用户上传规范文件；未提供时使用默认规范库，且**不作任何特殊处理**。 */
  standards_file_id: z.uuid().nullable().optional(),
  project: z
    .looseObject({
      name: z.string().trim().min(1),
      monitoring_unit: z.string().trim().min(1).optional(),
      construction_unit: z.string().trim().min(1).optional(),
      design_unit: z.string().trim().min(1).optional(),
    })
    .optional(),
  options: z
    .strictObject({
      expected_interval_days: z.number().positive().nullable().optional(),
      value_range: z
        .tuple([z.number().nullable(), z.number().nullable()])
        .nullable()
        .optional(),
    })
    .optional(),
});

export type CreateRunRequest = z.infer<typeof createRunRequestSchema>;

/**
 * 运行结果。`payload` 是引擎产出的日报接口载荷（`excavaguard.daily_report_input/v1`），
 * 本层**不生成日报正文与版式**，仅交付结构化载荷。
 */
export const runResultSchema = z.looseObject({
  run_id: z.uuid(),
  created_at: z.iso.datetime(),
  project_id: z.uuid(),
  monitoring_file_id: z.uuid(),
  standards_file_id: z.uuid().nullable(),
  /** 本次运行生效的规范来源说明（默认库 / 用户上传）。 */
  effective_standard_origin: z.string().nullable().optional(),
  engine: z.looseObject({
    elapsed_ms: z.number(),
    python: z.string().optional(),
    records: z.number(),
  }),
  payload: z.unknown(),
});

export type RunResult = z.infer<typeof runResultSchema>;
