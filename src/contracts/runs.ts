import { z } from "zod";
import { reportPeriodSchema, type ReportPeriod } from "@/contracts/report-period";
import {
  agentRunStateSchema,
  artifactRefSchema,
  supervisorActionSchema,
} from "@/contracts/agent-runtime";

/**
 * 分析任务（run）的请求与响应契约。
 *
 * 数据流：
 *   上传监测文件 → `monitoring_file_id`
 *   （可选）上传用户规范 → `standards_file_id`
 *   提供工程条件 → `context`
 *   → 确定性计算层（阶段一 数据准备 → 阶段二 确定性计算 → 阶段三 规范比对）
 *   → 日报或周期接口载荷 `daily_report_input/v1` / `period_report_input/v1`
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
  parent_run_id: z.uuid().optional(),
  monitoring_file_id: z.uuid(),
  report_date: z.iso.date(),
  report_period: reportPeriodSchema.optional(),
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
      /** 显式开启三 Agent 报告/审计链；默认仍只返回冻结引擎载荷。 */
      generate_report: z.boolean().optional(),
      /** AI 模式实际调用模型与 RAG；模板模式用于计算/表式调试。 */
      report_mode: z.enum(["ai", "template"]).optional(),
    })
    .optional(),
}).superRefine((value, ctx) => {
  if (value.report_period && value.report_date !== value.report_period.end_date) {
    ctx.addIssue({ code: "custom", path: ["report_date"], message: "周期报告日期必须等于区间结束日。" });
  }
});

export type CreateRunRequest = z.infer<typeof createRunRequestSchema>;

/**
 * 运行结果。`payload` 是引擎产出的日报或周期接口载荷（独立 v1 schema），
 * 默认仅交付结构化载荷；显式开启 `generate_report` 时，`agent_run` 携带报告、
 * 审计、人工复核状态与已通过审计的下载清单。
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
    source_records: z.number().optional(),
    daily_aggregation: z.unknown().nullable().optional(),
  }),
  payload: z.unknown(),
  agent_run: z
    .strictObject({
      state: agentRunStateSchema,
      terminal_action: supervisorActionSchema,
      steps: z.number().int().positive(),
      downloads: z.array(
        z.strictObject({
          kind: z.enum([
            "workbook",
            "cover_markdown",
            "appendices_markdown",
          ]),
          file_name: z.string().trim().min(1),
          sha256: z.string().regex(/^[a-f0-9]{64}$/),
          size_bytes: z.number().int().positive(),
          url: z.string().startsWith("/api/report-artifacts/"),
        }),
      ),
    })
    .nullable()
    .optional(),
});

export type RunResult = z.infer<typeof runResultSchema>;

export const reviewRequestSchema = z.strictObject({
  expected_revision: z.number().int().positive(),
  draft_ref: artifactRefSchema,
  decision: z.enum(["accepted", "needs_changes", "rejected"]),
  reason: z.string().trim().min(1).max(2000),
});

export const resumeRequestSchema = z.strictObject({
  expected_revision: z.number().int().positive(),
});

export const persistedRunSchema = z.strictObject({
  schema: z.literal("excavaguard.persisted_run/v1"),
  run_id: z.uuid(),
  revision: z.number().int().positive(),
  owner_id: z.literal("local-operator"),
  project_id: z.uuid(),
  created_at: z.iso.datetime(),
  updated_at: z.iso.datetime(),
  execution_status: z.enum(["running", "completed", "waiting", "failed"]),
  lease_until: z.iso.datetime().nullable(),
  request: createRunRequestSchema,
  result: runResultSchema.nullable(),
  error: z.strictObject({ code: z.string(), message: z.string() }).nullable(),
  review: z.strictObject({
    decision: reviewRequestSchema.shape.decision,
    reason: reviewRequestSchema.shape.reason,
    draft_ref: artifactRefSchema,
    submitted_at: z.iso.datetime(),
    owner_id: z.literal("local-operator"),
  }).nullable(),
}).superRefine((value, context) => {
  if (value.project_id !== value.request.project_id ||
      (value.result && (value.result.run_id !== value.run_id || value.result.project_id !== value.project_id)) ||
      (value.result?.agent_run && value.result.agent_run.state.run.run_id !== value.run_id)) {
    context.addIssue({ code: "custom", message: "运行与请求、结果的标识不一致。" });
  }
  const human = value.result?.agent_run?.state.human_review;
  const draft = value.result?.agent_run?.state.report_draft;
  if (value.review && (
    human?.decision !== value.review.decision ||
    JSON.stringify(draft?.ref) !== JSON.stringify(value.review.draft_ref)
  )) context.addIssue({ code: "custom", message: "复核记录必须绑定当前决定与草稿。" });
});

export type PersistedRun = z.output<typeof persistedRunSchema>;
export type ReviewRequest = z.output<typeof reviewRequestSchema>;
export type RunSummary = Pick<PersistedRun,
  "run_id" | "revision" | "created_at" | "updated_at" | "execution_status" | "error"
> & {
  report_date: string;
  project_name: string;
  agent_status: string | null;
  decision: ReviewRequest["decision"] | null;
  parent_run_id: string | null;
  report_period?: ReportPeriod;
};
