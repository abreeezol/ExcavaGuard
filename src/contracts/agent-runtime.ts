import { z } from "zod";
import { agentIdSchema } from "@/contracts/identifiers";

const nonEmptyText = z.string().trim().min(1);
const contentHashSchema = z.string().regex(/^[a-f0-9]{64}$/);

export const artifactRefSchema = z.strictObject({
  artifact_id: z.uuid(),
  schema: nonEmptyText,
  version: z.number().int().positive(),
  content_hash: contentHashSchema,
});

export const artifactEnvelopeSchema = z.strictObject({
  ref: artifactRefSchema,
  payload: z.unknown(),
});

export const supportingSnapshotSchema = z
  .strictObject({
    status: z.enum(["ready", "not_required", "insufficient", "unavailable"]),
    artifact: artifactEnvelopeSchema.nullable(),
    evidence_ids: z.array(nonEmptyText),
    gaps: z.array(nonEmptyText),
  })
  .superRefine((value, context) => {
    if (value.status === "ready" && value.artifact === null) {
      context.addIssue({
        code: "custom",
        path: ["artifact"],
        message: "ready 状态必须携带版本化产物。",
      });
    }
  });

export const factBindingSchema = z.strictObject({
  binding_id: nonEmptyText,
  report_path: nonEmptyText,
  fact_path: nonEmptyText,
  fact_value_hash: contentHashSchema,
});

export const citationBindingSchema = z.strictObject({
  citation_id: nonEmptyText,
  report_path: nonEmptyText,
  evidence_id: nonEmptyText,
});

export const reportDraftSchema = z.strictObject({
  ref: artifactRefSchema,
  source_refs: z.strictObject({
    engine: artifactRefSchema,
    evidence: artifactRefSchema.nullable(),
    analysis: artifactRefSchema.nullable(),
  }),
  fact_bindings: z.array(factBindingSchema),
  citations: z.array(citationBindingSchema),
  review_required: z.literal(true),
  payload: z.unknown(),
});

export const auditResponsibilitySchema = z.enum([
  "report-delivery",
  "supervisor",
  "human",
]);

export const auditIssueSchema = z.strictObject({
  issue_id: nonEmptyText,
  code: nonEmptyText,
  severity: z.enum(["error", "warning"]),
  blocking: z.boolean(),
  responsibility: auditResponsibilitySchema,
  path: nonEmptyText,
  message: nonEmptyText,
  expected: z.unknown().optional(),
  actual: z.unknown().optional(),
});

export const auditResultSchema = z.strictObject({
  ref: artifactRefSchema,
  draft_ref: artifactRefSchema,
  valid: z.boolean(),
  checks: z.array(
    z.strictObject({
      name: nonEmptyText,
      valid: z.boolean(),
      details: nonEmptyText.optional(),
    }),
  ),
  issues: z.array(auditIssueSchema),
});

export const traceEventSchema = z.strictObject({
  event_id: z.uuid(),
  agent: agentIdSchema,
  capability: nonEmptyText,
  status: z.enum(["success", "failed", "abstained", "invalidated"]),
  input_versions: z.record(z.string(), nonEmptyText),
  output_versions: z.record(z.string(), nonEmptyText),
  rule_ids: z.array(nonEmptyText),
  evidence_ids: z.array(nonEmptyText),
  error: z
    .strictObject({
      code: nonEmptyText,
      message: nonEmptyText,
    })
    .nullable(),
  return_reason: nonEmptyText.nullable(),
  started_at: z.iso.datetime(),
  finished_at: z.iso.datetime(),
});

export const agentRunStatusSchema = z.enum([
  "ready_for_report",
  "draft_ready",
  "revision_required",
  "awaiting_human_review",
  "stopped",
]);

export const agentRunStateSchema = z
  .strictObject({
    schema: z.literal("excavaguard.agent_state/v1"),
    run: z.strictObject({
      run_id: z.uuid(),
      status: agentRunStatusSchema,
      current_stage: z.enum(["report", "audit", "human_review", "stopped"]),
      revision_count: z.number().int().nonnegative(),
      created_at: z.iso.datetime(),
      updated_at: z.iso.datetime(),
    }),
    limits: z.strictObject({
      max_revision_rounds: z.number().int().min(0).max(10),
      max_model_calls: z.number().int().nonnegative(),
      model_calls_used: z.number().int().nonnegative(),
      deadline_at: z.iso.datetime(),
    }),
    engine_snapshot: artifactEnvelopeSchema,
    evidence_snapshot: supportingSnapshotSchema.nullable(),
    analysis_snapshot: supportingSnapshotSchema.nullable(),
    report_draft: reportDraftSchema.nullable(),
    audit_result: auditResultSchema.nullable(),
    human_review: z.strictObject({
      required: z.literal(true),
      reasons: z.array(nonEmptyText),
      submitted_at: z.iso.datetime().nullable(),
      decision: z.enum(["accepted", "needs_changes", "rejected"]).nullable(),
    }),
    trace: z.array(traceEventSchema),
  })
  .superRefine((value, context) => {
    const expectedStage = {
      ready_for_report: "report",
      draft_ready: "audit",
      revision_required: "report",
      awaiting_human_review: "human_review",
      stopped: "stopped",
    }[value.run.status];
    if (value.run.current_stage !== expectedStage) {
      context.addIssue({
        code: "custom",
        path: ["run", "current_stage"],
        message: "当前阶段与运行状态不一致。",
      });
    }
    if (value.run.revision_count > value.limits.max_revision_rounds) {
      context.addIssue({
        code: "custom",
        path: ["run", "revision_count"],
        message: "修订次数不能超过自动修订上限。",
      });
    }
    if (value.limits.model_calls_used > value.limits.max_model_calls) {
      context.addIssue({
        code: "custom",
        path: ["limits", "model_calls_used"],
        message: "模型调用次数不能超过调用预算。",
      });
    }
    if (value.report_draft === null && value.audit_result !== null) {
      context.addIssue({
        code: "custom",
        path: ["audit_result"],
        message: "没有草稿时不能保留审计结果。",
      });
    }
    if (
      value.run.status === "ready_for_report" &&
      (value.report_draft !== null || value.audit_result !== null)
    ) {
      context.addIssue({
        code: "custom",
        path: ["run", "status"],
        message: "待生成报告状态不能携带旧草稿或旧审计。",
      });
    }
    if (
      value.run.status === "draft_ready" &&
      (value.report_draft === null || value.audit_result !== null)
    ) {
      context.addIssue({
        code: "custom",
        path: ["run", "status"],
        message: "待审计状态必须只有当前草稿，不能已有审计结果。",
      });
    }
    if (
      value.report_draft &&
      value.audit_result &&
      (value.audit_result.draft_ref.artifact_id !== value.report_draft.ref.artifact_id ||
        value.audit_result.draft_ref.schema !== value.report_draft.ref.schema ||
        value.audit_result.draft_ref.version !== value.report_draft.ref.version ||
        value.audit_result.draft_ref.content_hash !== value.report_draft.ref.content_hash)
    ) {
      context.addIssue({
        code: "custom",
        path: ["audit_result", "draft_ref"],
        message: "审计结果必须绑定当前草稿版本。",
      });
    }
    if (
      value.run.status === "awaiting_human_review" &&
      value.audit_result?.valid !== true
    ) {
      context.addIssue({
        code: "custom",
        path: ["run", "status"],
        message: "进入工程师复核前必须存在已通过的审计结果。",
      });
    }
    if (
      value.run.status === "revision_required" &&
      value.audit_result?.valid !== false
    ) {
      context.addIssue({
        code: "custom",
        path: ["run", "status"],
        message: "修订状态必须绑定未通过的审计结果。",
      });
    }
  });

export const capabilityStateSchema = z.strictObject({
  available: z.boolean(),
  requires_model: z.boolean(),
  reason_code: nonEmptyText.nullable(),
});

export const agentCapabilitiesSchema = z.strictObject({
  render_report: capabilityStateSchema,
  validate_report: capabilityStateSchema,
});

export const supervisorActionSchema = z.strictObject({
  type: z.enum([
    "render_report",
    "audit_report",
    "revise_report",
    "wait_for_capability",
    "handoff_to_human",
  ]),
  agent: agentIdSchema,
  reason_code: z.enum([
    "READY_TO_RENDER",
    "READY_TO_AUDIT",
    "REPORT_REVISION_REQUIRED",
    "CAPABILITY_UNAVAILABLE",
    "AUDIT_PASSED",
    "UPSTREAM_ISSUE_REQUIRES_HUMAN",
    "REVISION_LIMIT_REACHED",
    "MODEL_CALL_BUDGET_EXHAUSTED",
    "DEADLINE_EXCEEDED",
    "RUN_STOPPED",
  ]),
  details: nonEmptyText,
});

export type ArtifactRef = z.output<typeof artifactRefSchema>;
export type ArtifactEnvelope = z.output<typeof artifactEnvelopeSchema>;
export type SupportingSnapshot = z.output<typeof supportingSnapshotSchema>;
export type ReportDraft = z.output<typeof reportDraftSchema>;
export type AuditResult = z.output<typeof auditResultSchema>;
export type TraceEvent = z.output<typeof traceEventSchema>;
export type AgentRunState = z.output<typeof agentRunStateSchema>;
export type AgentCapabilities = z.output<typeof agentCapabilitiesSchema>;
export type SupervisorAction = z.output<typeof supervisorActionSchema>;
