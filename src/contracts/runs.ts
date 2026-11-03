import { z } from "zod";
import { actorSchema } from "@/contracts/actor";
import { storedFileSchema } from "@/contracts/monitoring-files";
import { projectStandardDocumentSchema } from "@/contracts/project-standards";
import { reportPeriodSchema } from "@/contracts/report-period";
import {
  agentRunStateSchema,
  artifactRefSchema,
  supervisorActionSchema,
} from "@/contracts/agent-runtime";
import {
  engineerRiskEvaluationInputSchema,
  engineerRiskEvaluationSchema,
  riskEvaluationTargets,
} from "@/contracts/engineer-evaluation";

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
  additional_monitoring_file_ids: z.array(z.uuid()).max(9).optional(),
  report_date: z.iso.date(),
  report_period: reportPeriodSchema.optional(),
  context: projectContextSchema,
  /** 用户上传规范文件；未提供时使用默认规范库，且**不作任何特殊处理**。 */
  standards_file_id: z.uuid().nullable().optional(),
  /** Omit: all enabled standards in this project; []: explicitly none. Frozen at run creation. */
  project_standard_ids: z.array(z.uuid()).max(50).optional(),
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
  const fileIds = [value.monitoring_file_id, ...(value.additional_monitoring_file_ids ?? [])];
  if (new Set(fileIds).size !== fileIds.length) {
    ctx.addIssue({ code: "custom", path: ["additional_monitoring_file_ids"], message: "监测文件不能重复选择。" });
  }
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
  project_standards: z.array(projectStandardDocumentSchema).optional(),
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
  evaluations: z.array(engineerRiskEvaluationInputSchema).max(500).optional(),
}).superRefine((value, context) => {
  const indexes = value.evaluations?.map((evaluation) => evaluation.risk_item_index) ?? [];
  if (new Set(indexes).size !== indexes.length) {
    context.addIssue({
      code: "custom",
      path: ["evaluations"],
      message: "同一风险条目只能提交一条工程师评价。",
    });
  }
});

export const resumeRequestSchema = z.strictObject({
  expected_revision: z.number().int().positive(),
});

export const deleteRunRequestSchema = z.strictObject({
  expected_revision: z.number().int().positive(),
});

export const saveEvaluationRequestSchema = z.strictObject({
  expected_revision: z.number().int().positive(),
  draft_ref: artifactRefSchema,
  evaluations: z.array(engineerRiskEvaluationInputSchema).min(1).max(500),
  reason: z.string().trim().max(2000).optional(),
}).superRefine((value, context) => {
  if (new Set(value.evaluations.map(item => item.risk_item_index)).size !== value.evaluations.length) {
    context.addIssue({ code: "custom", path: ["evaluations"], message: "同一风险条目只能提交一条评价。" });
  }
});

export const sharedEvaluationSchema = engineerRiskEvaluationSchema.extend({
  evaluated_by: actorSchema,
  evaluated_at: z.iso.datetime(),
});

export const persistedRunSchema = z.strictObject({
  schema: z.literal("excavaguard.persisted_run/v1"),
  run_id: z.uuid(),
  revision: z.number().int().positive(),
  owner_id: z.union([z.literal("local-operator"), z.uuid()]),
  created_by: actorSchema.optional(),
  source_files: z.array(storedFileSchema).min(1).max(10).optional(),
  risk_evaluation_total: z.number().int().nonnegative().optional(),
  evaluation_draft: z.strictObject({
    draft_ref: artifactRefSchema,
    evaluations: z.array(sharedEvaluationSchema).max(500),
    updated_by: actorSchema,
    updated_at: z.iso.datetime(),
    reason: z.string().max(2000).optional(),
  }).nullable().optional(),
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
    evaluations: z.array(engineerRiskEvaluationSchema).max(500).default([]),
    draft_ref: artifactRefSchema,
    submitted_at: z.iso.datetime(),
    owner_id: z.union([z.literal("local-operator"), z.uuid()]),
    submitted_by: actorSchema.optional(),
  }).nullable(),
}).superRefine((value, context) => {
  if (value.project_id !== value.request.project_id ||
      (value.result && (value.result.run_id !== value.run_id || value.result.project_id !== value.project_id)) ||
      (value.result?.agent_run && value.result.agent_run.state.run.run_id !== value.run_id)) {
    context.addIssue({ code: "custom", message: "运行与请求、结果的标识不一致。" });
  }
  const human = value.result?.agent_run?.state.human_review;
  const draft = value.result?.agent_run?.state.report_draft;
  if (value.created_by && value.created_by.id !== value.owner_id) {
    context.addIssue({ code: "custom", message: "生成者必须与运行创建者一致。" });
  }
  if (value.review?.submitted_by && value.review.submitted_by.id !== value.review.owner_id) {
    context.addIssue({ code: "custom", message: "复核提交者标识不一致。" });
  }
  if (value.source_files) {
    const ids = [value.request.monitoring_file_id, ...(value.request.additional_monitoring_file_ids ?? [])];
    if (value.source_files.length !== ids.length || value.source_files.some((file, index) =>
      file.file_id !== ids[index] || file.project_id !== value.project_id || file.kind !== "monitoring"
    )) context.addIssue({ code: "custom", message: "输入文件清单必须绑定当前工程和运行请求。" });
  }
  if (value.evaluation_draft && JSON.stringify(value.evaluation_draft.draft_ref) !== JSON.stringify(draft?.ref)) {
    context.addIssue({ code: "custom", message: "暂存评价必须绑定当前草稿。" });
  }
  if (value.review && (
    human?.decision !== value.review.decision ||
    JSON.stringify(draft?.ref) !== JSON.stringify(value.review.draft_ref)
  )) context.addIssue({ code: "custom", message: "复核记录必须绑定当前决定与草稿。" });
  const targets = new Map(
    riskEvaluationTargets(value.result?.payload).map(target => [target.risk_item_index, target]),
  );
  if (value.risk_evaluation_total !== undefined && value.risk_evaluation_total !== targets.size) {
    context.addIssue({ code: "custom", message: "风险评价总数必须与冻结事实一致。" });
  }
  for (const evaluations of [value.review?.evaluations, value.evaluation_draft?.evaluations]) {
    if (evaluations?.length) {
      const indexes = evaluations.map(evaluation => evaluation.risk_item_index);
      if (new Set(indexes).size !== indexes.length ||
          evaluations.some(evaluation => {
            const target = targets.get(evaluation.risk_item_index);
            return !target ||
              target.point_id !== evaluation.point_id ||
              target.metric_key !== evaluation.metric_key ||
              target.metric_name !== evaluation.metric_name ||
              target.timestamp !== evaluation.timestamp ||
              target.risk_level !== evaluation.risk_level;
          })) {
        context.addIssue({ code: "custom", message: "工程师评价必须逐项绑定当前冻结风险事实。" });
      }
    }
  }
});

export type PersistedRun = z.output<typeof persistedRunSchema>;
export type ReviewRequest = z.output<typeof reviewRequestSchema>;
export type SaveEvaluationRequest = z.infer<typeof saveEvaluationRequestSchema>;
export const runSummarySchema = z.strictObject({
  run_id: z.uuid(),
  revision: z.number().int().positive(),
  created_at: z.iso.datetime(),
  updated_at: z.iso.datetime(),
  execution_status: persistedRunSchema.shape.execution_status,
  error: persistedRunSchema.shape.error,
  report_date: z.string(),
  project_name: z.string(),
  agent_status: z.string().nullable(),
  decision: reviewRequestSchema.shape.decision.nullable(),
  parent_run_id: z.uuid().nullable(),
  report_period: reportPeriodSchema.optional(),
  created_by: actorSchema.nullable().optional(),
  reviewed_by: actorSchema.nullable().optional(),
  evaluation_count: z.number().int().nonnegative().optional(),
  risk_evaluation_total: z.number().int().nonnegative().nullable().optional(),
});
export const runListResponseSchema = z.strictObject({ runs: z.array(runSummarySchema).max(100) });
export type RunSummary = z.infer<typeof runSummarySchema>;
