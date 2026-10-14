import "server-only";
import { randomUUID } from "node:crypto";
import {
  agentCapabilitiesSchema,
  agentRunStateSchema,
  auditResultSchema,
  reportDraftSchema,
  supportingSnapshotSchema,
  supervisorActionSchema,
  traceEventSchema,
  type AgentCapabilities,
  type AgentRunState,
  type ArtifactEnvelope,
  type ArtifactRef,
  type AuditResult,
  type ReportDraft,
  type SupportingSnapshot,
  type SupervisorAction,
  type TraceEvent,
} from "@/contracts/agent-runtime";
import type { AgentId } from "@/contracts/identifiers";

export class AgentStateError extends Error {
  constructor(
    readonly code:
      | "INVALID_LIMITS"
      | "INVALID_TIMESTAMP"
      | "INVALID_TRANSITION"
      | "STALE_ARTIFACT"
      | "REVISION_LIMIT_REACHED"
      | "MODEL_CALL_BUDGET_EXHAUSTED"
      | "INCONSISTENT_AUDIT",
    message: string,
  ) {
    super(message);
    this.name = "AgentStateError";
  }
}

type CreateAgentRunStateInput = {
  runId: string;
  createdAt: string;
  deadlineAt: string;
  maxModelCalls: number;
  engineSnapshot: ArtifactEnvelope;
  evidenceSnapshot?: SupportingSnapshot | null;
  analysisSnapshot?: SupportingSnapshot | null;
  maxRevisionRounds?: number;
};

function refVersion(ref: ArtifactRef): string {
  return `${ref.schema}@${ref.version}:${ref.artifact_id}:${ref.content_hash}`;
}

function sameRef(left: ArtifactRef | null, right: ArtifactRef | null): boolean {
  if (left === null || right === null) {
    return left === right;
  }
  return (
    left.artifact_id === right.artifact_id &&
    left.schema === right.schema &&
    left.version === right.version &&
    left.content_hash === right.content_hash
  );
}

function supportingRef(snapshot: SupportingSnapshot | null): ArtifactRef | null {
  return snapshot?.artifact?.ref ?? null;
}

function parseState(state: AgentRunState): AgentRunState {
  return agentRunStateSchema.parse(state);
}

function createTraceEvent(input: {
  agent: AgentId;
  capability: string;
  status: TraceEvent["status"];
  inputVersions?: Record<string, string>;
  outputVersions?: Record<string, string>;
  ruleIds?: string[];
  evidenceIds?: string[];
  error?: TraceEvent["error"];
  returnReason?: string | null;
  at: string;
}): TraceEvent {
  return traceEventSchema.parse({
    event_id: randomUUID(),
    agent: input.agent,
    capability: input.capability,
    status: input.status,
    input_versions: input.inputVersions ?? {},
    output_versions: input.outputVersions ?? {},
    rule_ids: input.ruleIds ?? [],
    evidence_ids: input.evidenceIds ?? [],
    error: input.error ?? null,
    return_reason: input.returnReason ?? null,
    started_at: input.at,
    finished_at: input.at,
  });
}

function assertDraftSources(state: AgentRunState, draft: ReportDraft): void {
  if (!sameRef(draft.source_refs.engine, state.engine_snapshot.ref)) {
    throw new AgentStateError("STALE_ARTIFACT", "草稿引用的引擎事实快照已过期。");
  }
  if (!sameRef(draft.source_refs.evidence, supportingRef(state.evidence_snapshot))) {
    throw new AgentStateError("STALE_ARTIFACT", "草稿引用的证据快照已过期。");
  }
  if (!sameRef(draft.source_refs.analysis, supportingRef(state.analysis_snapshot))) {
    throw new AgentStateError("STALE_ARTIFACT", "草稿引用的分析快照已过期。");
  }
}

function requireCapability(
  action: SupervisorAction,
  capability: AgentCapabilities["render_report"],
  state: AgentRunState,
): SupervisorAction {
  if (!capability.available) {
    return supervisorActionSchema.parse({
      type: "wait_for_capability",
      agent: action.agent,
      reason_code: "CAPABILITY_UNAVAILABLE",
      details: capability.reason_code ?? "所需能力尚未实现或配置。",
    });
  }
  if (
    capability.requires_model &&
    state.limits.model_calls_used >= state.limits.max_model_calls
  ) {
    return supervisorActionSchema.parse({
      type: "handoff_to_human",
      agent: "supervisor",
      reason_code: "MODEL_CALL_BUDGET_EXHAUSTED",
      details: "模型调用预算已耗尽，停止自动处理并转工程师复核。",
    });
  }
  return action;
}

export function createAgentRunState(input: CreateAgentRunStateInput): AgentRunState {
  const maxRevisionRounds = input.maxRevisionRounds ?? 2;
  const createdAtMs = Date.parse(input.createdAt);
  const deadlineAtMs = Date.parse(input.deadlineAt);
  if (!Number.isFinite(createdAtMs) || !Number.isFinite(deadlineAtMs)) {
    throw new AgentStateError("INVALID_TIMESTAMP", "运行时间必须是有效日期时间。");
  }
  if (deadlineAtMs <= createdAtMs) {
    throw new AgentStateError("INVALID_LIMITS", "截止时间必须晚于运行创建时间。");
  }

  return agentRunStateSchema.parse({
    schema: "excavaguard.agent_state/v1",
    run: {
      run_id: input.runId,
      status: "ready_for_report",
      current_stage: "report",
      revision_count: 0,
      created_at: input.createdAt,
      updated_at: input.createdAt,
    },
    limits: {
      max_revision_rounds: maxRevisionRounds,
      max_model_calls: input.maxModelCalls,
      model_calls_used: 0,
      deadline_at: input.deadlineAt,
    },
    engine_snapshot: input.engineSnapshot,
    evidence_snapshot: input.evidenceSnapshot ?? null,
    analysis_snapshot: input.analysisSnapshot ?? null,
    report_draft: null,
    audit_result: null,
    human_review: {
      required: true,
      reasons: [],
      submitted_at: null,
      decision: null,
    },
    trace: [],
  });
}

export function decideNextAction(
  rawState: AgentRunState,
  rawCapabilities: AgentCapabilities,
  now: string,
): SupervisorAction {
  const state = parseState(rawState);
  const capabilities = agentCapabilitiesSchema.parse(rawCapabilities);
  const nowMs = Date.parse(now);
  if (!Number.isFinite(nowMs)) {
    throw new AgentStateError("INVALID_TIMESTAMP", "决策时间必须是有效日期时间。");
  }

  if (nowMs >= Date.parse(state.limits.deadline_at)) {
    return supervisorActionSchema.parse({
      type: "handoff_to_human",
      agent: "supervisor",
      reason_code: "DEADLINE_EXCEEDED",
      details: "运行时间预算已到，停止自动处理并转工程师复核。",
    });
  }

  if (state.run.status === "stopped") {
    return supervisorActionSchema.parse({
      type: "handoff_to_human",
      agent: "supervisor",
      reason_code: "RUN_STOPPED",
      details: "自动流程已停止，保留当前产物并转工程师处理。",
    });
  }

  if (state.audit_result?.valid) {
    return supervisorActionSchema.parse({
      type: "handoff_to_human",
      agent: "supervisor",
      reason_code: "AUDIT_PASSED",
      details: "独立审计已通过，草稿仍需工程师复核。",
    });
  }

  if (state.audit_result && !state.audit_result.valid) {
    const blockingIssues = state.audit_result.issues.filter((issue) => issue.blocking);
    const hasUpstreamIssue = blockingIssues.some(
      (issue) => issue.responsibility !== "report-delivery",
    );
    if (hasUpstreamIssue) {
      return supervisorActionSchema.parse({
        type: "handoff_to_human",
        agent: "supervisor",
        reason_code: "UPSTREAM_ISSUE_REQUIRES_HUMAN",
        details: "审计问题不属于报告自动修订范围，审计不得修改源事实。",
      });
    }
    if (state.run.revision_count >= state.limits.max_revision_rounds) {
      return supervisorActionSchema.parse({
        type: "handoff_to_human",
        agent: "supervisor",
        reason_code: "REVISION_LIMIT_REACHED",
        details: "报告自动修订已达到上限，保留审计问题并转工程师复核。",
      });
    }
    return requireCapability(
      supervisorActionSchema.parse({
        type: "revise_report",
        agent: "report-delivery",
        reason_code: "REPORT_REVISION_REQUIRED",
        details: "仅将报告责任问题退回报告交付 Agent。",
      }),
      capabilities.render_report,
      state,
    );
  }

  if (state.report_draft) {
    return requireCapability(
      supervisorActionSchema.parse({
        type: "audit_report",
        agent: "audit",
        reason_code: "READY_TO_AUDIT",
        details: "草稿已绑定当前事实版本，进入独立审计。",
      }),
      capabilities.validate_report,
      state,
    );
  }

  return requireCapability(
    supervisorActionSchema.parse({
      type: "render_report",
      agent: "report-delivery",
      reason_code: "READY_TO_RENDER",
      details: "引擎事实快照已就绪，可以生成首版草稿。",
    }),
    capabilities.render_report,
    state,
  );
}

export function replaceEngineSnapshot(
  rawState: AgentRunState,
  engineSnapshot: ArtifactEnvelope,
  at: string,
): AgentRunState {
  const state = parseState(rawState);
  const previous = state.engine_snapshot.ref;
  return agentRunStateSchema.parse({
    ...state,
    run: {
      ...state.run,
      status: "ready_for_report",
      current_stage: "report",
      revision_count: 0,
      updated_at: at,
    },
    engine_snapshot: engineSnapshot,
    evidence_snapshot: null,
    analysis_snapshot: null,
    report_draft: null,
    audit_result: null,
    human_review: { ...state.human_review, reasons: [], submitted_at: null, decision: null },
    trace: [
      ...state.trace,
      createTraceEvent({
        agent: "supervisor",
        capability: "replace-engine-snapshot",
        status: "invalidated",
        inputVersions: { engine: refVersion(previous) },
        outputVersions: { engine: refVersion(engineSnapshot.ref) },
        returnReason: "ENGINE_SNAPSHOT_CHANGED",
        at,
      }),
    ],
  });
}

export function replaceEvidenceSnapshot(
  rawState: AgentRunState,
  rawSnapshot: SupportingSnapshot,
  at: string,
): AgentRunState {
  const state = parseState(rawState);
  const snapshot = supportingSnapshotSchema.parse(rawSnapshot);
  return agentRunStateSchema.parse({
    ...state,
    run: {
      ...state.run,
      status: "ready_for_report",
      current_stage: "report",
      revision_count: 0,
      updated_at: at,
    },
    evidence_snapshot: snapshot,
    analysis_snapshot: null,
    report_draft: null,
    audit_result: null,
    human_review: { ...state.human_review, reasons: [], submitted_at: null, decision: null },
    trace: [
      ...state.trace,
      createTraceEvent({
        agent: "supervisor",
        capability: "replace-evidence-snapshot",
        status: "invalidated",
        outputVersions: snapshot.artifact
          ? { evidence: refVersion(snapshot.artifact.ref) }
          : {},
        evidenceIds: snapshot.evidence_ids,
        returnReason: "EVIDENCE_SNAPSHOT_CHANGED",
        at,
      }),
    ],
  });
}

export function replaceAnalysisSnapshot(
  rawState: AgentRunState,
  rawSnapshot: SupportingSnapshot,
  at: string,
): AgentRunState {
  const state = parseState(rawState);
  const snapshot = supportingSnapshotSchema.parse(rawSnapshot);
  return agentRunStateSchema.parse({
    ...state,
    run: {
      ...state.run,
      status: "ready_for_report",
      current_stage: "report",
      revision_count: 0,
      updated_at: at,
    },
    analysis_snapshot: snapshot,
    report_draft: null,
    audit_result: null,
    human_review: { ...state.human_review, reasons: [], submitted_at: null, decision: null },
    trace: [
      ...state.trace,
      createTraceEvent({
        agent: "supervisor",
        capability: "replace-analysis-snapshot",
        status: "invalidated",
        outputVersions: snapshot.artifact
          ? { analysis: refVersion(snapshot.artifact.ref) }
          : {},
        evidenceIds: snapshot.evidence_ids,
        returnReason: "ANALYSIS_SNAPSHOT_CHANGED",
        at,
      }),
    ],
  });
}

export function recordReportDraft(
  rawState: AgentRunState,
  rawDraft: ReportDraft,
  at: string,
): AgentRunState {
  const state = parseState(rawState);
  const draft = reportDraftSchema.parse(rawDraft);
  assertDraftSources(state, draft);
  const isRevision = state.report_draft !== null;
  if (!isRevision && state.run.status !== "ready_for_report") {
    throw new AgentStateError(
      "INVALID_TRANSITION",
      "只有待生成报告状态可以写入首版草稿。",
    );
  }
  if (
    isRevision &&
    (state.run.status !== "revision_required" || state.audit_result?.valid !== false)
  ) {
    throw new AgentStateError(
      "INVALID_TRANSITION",
      "只有未通过审计的草稿可以进入自动修订。",
    );
  }
  if (isRevision && state.run.revision_count >= state.limits.max_revision_rounds) {
    throw new AgentStateError(
      "REVISION_LIMIT_REACHED",
      "报告自动修订已达到上限，不能继续写入自动修订草稿。",
    );
  }
  const evidenceRef = supportingRef(state.evidence_snapshot);
  const analysisRef = supportingRef(state.analysis_snapshot);

  return agentRunStateSchema.parse({
    ...state,
    run: {
      ...state.run,
      status: "draft_ready",
      current_stage: "audit",
      revision_count: state.run.revision_count + (isRevision ? 1 : 0),
      updated_at: at,
    },
    report_draft: draft,
    audit_result: null,
    human_review: { ...state.human_review, reasons: [], submitted_at: null, decision: null },
    trace: [
      ...state.trace,
      createTraceEvent({
        agent: "report-delivery",
        capability: isRevision ? "revise-daily-report" : "render-daily-report",
        status: "success",
        inputVersions: {
          engine: refVersion(state.engine_snapshot.ref),
          ...(evidenceRef ? { evidence: refVersion(evidenceRef) } : {}),
          ...(analysisRef ? { analysis: refVersion(analysisRef) } : {}),
        },
        outputVersions: { report_draft: refVersion(draft.ref) },
        evidenceIds: draft.citations.map((citation) => citation.evidence_id),
        at,
      }),
    ],
  });
}

export function recordAuditResult(
  rawState: AgentRunState,
  rawAudit: AuditResult,
  at: string,
): AgentRunState {
  const state = parseState(rawState);
  const audit = auditResultSchema.parse(rawAudit);
  if (state.run.status !== "draft_ready" || state.audit_result !== null) {
    throw new AgentStateError(
      "INVALID_TRANSITION",
      "只有尚未审计的当前草稿可以写入审计结果。",
    );
  }
  if (!state.report_draft || !sameRef(audit.draft_ref, state.report_draft.ref)) {
    throw new AgentStateError("STALE_ARTIFACT", "审计结果对应的草稿已失效。");
  }
  const hasBlockingIssue = audit.issues.some((issue) => issue.blocking);
  if (audit.valid === hasBlockingIssue) {
    throw new AgentStateError(
      "INCONSISTENT_AUDIT",
      "审计 valid 与阻断问题清单不一致。",
    );
  }

  return agentRunStateSchema.parse({
    ...state,
    run: {
      ...state.run,
      status: audit.valid ? "awaiting_human_review" : "revision_required",
      current_stage: audit.valid ? "human_review" : "report",
      updated_at: at,
    },
    audit_result: audit,
    human_review: {
      ...state.human_review,
      reasons: audit.valid
        ? ["AUDIT_PASSED_ENGINEER_REVIEW_REQUIRED"]
        : audit.issues.filter((issue) => issue.blocking).map((issue) => issue.code),
      submitted_at: null,
      decision: null,
    },
    trace: [
      ...state.trace,
      createTraceEvent({
        agent: "audit",
        capability: "validate-report",
        status: audit.valid ? "success" : "failed",
        inputVersions: { report_draft: refVersion(state.report_draft.ref) },
        outputVersions: { audit_result: refVersion(audit.ref) },
        evidenceIds: state.report_draft.citations.map(
          (citation) => citation.evidence_id,
        ),
        returnReason: audit.valid ? "AUDIT_PASSED" : "AUDIT_ISSUES_FOUND",
        at,
      }),
    ],
  });
}

export function recordModelCall(
  rawState: AgentRunState,
  at: string,
): AgentRunState {
  const state = parseState(rawState);
  if (
    state.run.status === "awaiting_human_review" ||
    state.run.status === "stopped"
  ) {
    throw new AgentStateError(
      "INVALID_TRANSITION",
      "自动流程结束后不能继续发起模型调用。",
    );
  }
  if (state.limits.model_calls_used >= state.limits.max_model_calls) {
    throw new AgentStateError(
      "MODEL_CALL_BUDGET_EXHAUSTED",
      "模型调用预算已耗尽，不能继续发起模型调用。",
    );
  }
  return agentRunStateSchema.parse({
    ...state,
    run: { ...state.run, updated_at: at },
    limits: {
      ...state.limits,
      model_calls_used: state.limits.model_calls_used + 1,
    },
  });
}

export function recordCapabilityFailure(
  rawState: AgentRunState,
  input: {
    agent: AgentId;
    capability: string;
    code: string;
    message: string;
    at: string;
  },
): AgentRunState {
  const state = parseState(rawState);
  const inputVersions = {
    engine: refVersion(state.engine_snapshot.ref),
    ...(state.report_draft
      ? { report_draft: refVersion(state.report_draft.ref) }
      : {}),
  };
  return agentRunStateSchema.parse({
    ...state,
    run: { ...state.run, updated_at: input.at },
    trace: [
      ...state.trace,
      createTraceEvent({
        agent: input.agent,
        capability: input.capability,
        status: "failed",
        inputVersions,
        error: { code: input.code, message: input.message },
        returnReason: "CAPABILITY_UNAVAILABLE",
        at: input.at,
      }),
    ],
  });
}
