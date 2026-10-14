import { randomUUID } from "node:crypto";
import { describe, expect, it } from "vitest";
import type {
  AgentCapabilities,
  AgentRunState,
  ArtifactEnvelope,
  ArtifactRef,
  AuditResult,
  ReportDraft,
  SupportingSnapshot,
} from "@/contracts/agent-runtime";
import {
  AgentStateError,
  createAgentRunState,
  decideNextAction,
  recordAuditResult,
  recordCapabilityFailure,
  recordModelCall,
  recordReportDraft,
  replaceAnalysisSnapshot,
  replaceEngineSnapshot,
  replaceEvidenceSnapshot,
} from "@/server/agents/supervisor";

const CREATED_AT = "2026-10-12T01:00:00.000Z";
const BEFORE_DEADLINE = "2026-10-12T01:10:00.000Z";
const DEADLINE_AT = "2026-10-12T01:30:00.000Z";
const AFTER_DEADLINE = "2026-10-12T01:31:00.000Z";

function ref(schema: string, version: number, hashChar: string): ArtifactRef {
  return {
    artifact_id: randomUUID(),
    schema,
    version,
    content_hash: hashChar.repeat(64),
  };
}

function envelope(schema: string, version: number, hashChar: string): ArtifactEnvelope {
  return {
    ref: ref(schema, version, hashChar),
    payload: { schema, version },
  };
}

function supporting(
  schema: string,
  version: number,
  hashChar: string,
  evidenceIds: string[] = [],
): SupportingSnapshot {
  return {
    status: "ready",
    artifact: envelope(schema, version, hashChar),
    evidence_ids: evidenceIds,
    gaps: [],
  };
}

function createState(maxRevisionRounds = 2, maxModelCalls = 4): AgentRunState {
  return createAgentRunState({
    runId: randomUUID(),
    createdAt: CREATED_AT,
    deadlineAt: DEADLINE_AT,
    maxModelCalls,
    maxRevisionRounds,
    engineSnapshot: envelope("excavaguard.daily_report_input/v1", 1, "a"),
  });
}

function draftFor(
  state: AgentRunState,
  version: number,
  hashChar: string,
): ReportDraft {
  const draftRef = ref("excavaguard.report_draft/v1", version, hashChar);
  const artifactPath = `var/report-artifacts/${draftRef.artifact_id}`;
  return {
    ref: draftRef,
    source_refs: {
      engine: state.engine_snapshot.ref,
      evidence: state.evidence_snapshot?.artifact?.ref ?? null,
      analysis: state.analysis_snapshot?.artifact?.ref ?? null,
    },
    fact_bindings: [
      {
        binding_id: "binding-1",
        report_path: "sections.monitoring.items.0.current",
        fact_path: "items.0.current",
        fact_value_hash: "f".repeat(64),
      },
    ],
    artifacts: [
      {
        kind: "workbook",
        file_name: "监测日报_测试_草稿.xlsx",
        relative_path: `${artifactPath}/监测日报_测试_草稿.xlsx`,
        media_type:
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        sha256: "1".repeat(64),
        size_bytes: 1,
        sheets: ["监测日报"],
      },
      {
        kind: "cover_markdown",
        file_name: "监测日报_测试_草稿_封面.md",
        relative_path: `${artifactPath}/监测日报_测试_草稿_封面.md`,
        media_type: "text/markdown; charset=utf-8",
        sha256: "2".repeat(64),
        size_bytes: 1,
        sheets: [],
      },
      {
        kind: "appendices_markdown",
        file_name: "监测日报_测试_草稿_附表及清单.md",
        relative_path: `${artifactPath}/监测日报_测试_草稿_附表及清单.md`,
        media_type: "text/markdown; charset=utf-8",
        sha256: "3".repeat(64),
        size_bytes: 1,
        sheets: [],
      },
    ],
    artifact_bindings: [],
    citations: state.evidence_snapshot?.evidence_ids.map((evidenceId, index) => ({
      citation_id: `citation-${index + 1}`,
      report_path: "sections.basis",
      evidence_id: evidenceId,
    })) ?? [],
    review_required: true,
    payload: { title: "监测日报草稿" },
  };
}

function auditFor(
  draft: ReportDraft,
  valid: boolean,
  responsibility: "report-delivery" | "supervisor" | "human" = "report-delivery",
  version = 1,
): AuditResult {
  return {
    ref: ref("excavaguard.audit_result/v1", version, valid ? "b" : "c"),
    draft_ref: draft.ref,
    valid,
    checks: [{ name: "fact-bindings", valid }],
    issues: valid
      ? []
      : [
          {
            issue_id: `issue-${version}`,
            code: responsibility === "report-delivery" ? "NUMBER_MISMATCH" : "UPSTREAM_GAP",
            severity: "error",
            blocking: true,
            responsibility,
            path: "sections.monitoring.items.0.current",
            message: "审计发现阻断问题。",
          },
        ],
  };
}

const AVAILABLE: AgentCapabilities = {
  render_report: { available: true, requires_model: false, reason_code: null },
  validate_report: { available: true, requires_model: false, reason_code: null },
};

describe("三 Agent Supervisor 状态机", () => {
  it("报告 Skill 未实现时明确等待，不伪造草稿", () => {
    const state = createState();
    const action = decideNextAction(
      state,
      {
        ...AVAILABLE,
        render_report: {
          available: false,
          requires_model: false,
          reason_code: "SKILL_NOT_IMPLEMENTED",
        },
      },
      BEFORE_DEADLINE,
    );

    expect(action).toMatchObject({
      type: "wait_for_capability",
      agent: "report-delivery",
      reason_code: "CAPABILITY_UNAVAILABLE",
      details: "SKILL_NOT_IMPLEMENTED",
    });
    expect(state.report_draft).toBeNull();
  });

  it("按事实快照生成草稿，草稿完成后进入独立审计", () => {
    let state = createState();
    expect(decideNextAction(state, AVAILABLE, BEFORE_DEADLINE).type).toBe(
      "render_report",
    );

    const draft = draftFor(state, 1, "d");
    state = recordReportDraft(state, draft, BEFORE_DEADLINE);

    expect(state.run.status).toBe("draft_ready");
    expect(state.run.current_stage).toBe("audit");
    expect(state.run.revision_count).toBe(0);
    expect(decideNextAction(state, AVAILABLE, BEFORE_DEADLINE)).toMatchObject({
      type: "audit_report",
      agent: "audit",
      reason_code: "READY_TO_AUDIT",
    });
  });

  it("审计通过后仍只交工程师复核，不自动签发", () => {
    let state = createState();
    const draft = draftFor(state, 1, "d");
    state = recordReportDraft(state, draft, BEFORE_DEADLINE);
    state = recordAuditResult(state, auditFor(draft, true), BEFORE_DEADLINE);

    expect(state.run.status).toBe("awaiting_human_review");
    expect(state.human_review.required).toBe(true);
    expect(decideNextAction(state, AVAILABLE, BEFORE_DEADLINE)).toMatchObject({
      type: "handoff_to_human",
      reason_code: "AUDIT_PASSED",
    });
  });

  it("报告问题最多自动修订两轮，达到上限后人工接管", () => {
    let state = createState(2);

    const firstDraft = draftFor(state, 1, "d");
    state = recordReportDraft(state, firstDraft, BEFORE_DEADLINE);
    state = recordAuditResult(
      state,
      auditFor(firstDraft, false, "report-delivery", 1),
      BEFORE_DEADLINE,
    );
    expect(decideNextAction(state, AVAILABLE, BEFORE_DEADLINE).type).toBe(
      "revise_report",
    );

    const secondDraft = draftFor(state, 2, "e");
    state = recordReportDraft(state, secondDraft, BEFORE_DEADLINE);
    state = recordAuditResult(
      state,
      auditFor(secondDraft, false, "report-delivery", 2),
      BEFORE_DEADLINE,
    );
    expect(state.run.revision_count).toBe(1);
    expect(decideNextAction(state, AVAILABLE, BEFORE_DEADLINE).type).toBe(
      "revise_report",
    );

    const thirdDraft = draftFor(state, 3, "f");
    state = recordReportDraft(state, thirdDraft, BEFORE_DEADLINE);
    state = recordAuditResult(
      state,
      auditFor(thirdDraft, false, "report-delivery", 3),
      BEFORE_DEADLINE,
    );

    expect(state.run.revision_count).toBe(2);
    expect(decideNextAction(state, AVAILABLE, BEFORE_DEADLINE)).toMatchObject({
      type: "handoff_to_human",
      reason_code: "REVISION_LIMIT_REACHED",
    });
    expect(() =>
      recordReportDraft(state, draftFor(state, 4, "1"), BEFORE_DEADLINE),
    ).toThrowError(AgentStateError);
  });

  it("上游责任问题不退给报告 Agent，直接交工程师", () => {
    let state = createState();
    const draft = draftFor(state, 1, "d");
    state = recordReportDraft(state, draft, BEFORE_DEADLINE);
    state = recordAuditResult(
      state,
      auditFor(draft, false, "supervisor"),
      BEFORE_DEADLINE,
    );

    expect(decideNextAction(state, AVAILABLE, BEFORE_DEADLINE)).toMatchObject({
      type: "handoff_to_human",
      reason_code: "UPSTREAM_ISSUE_REQUIRES_HUMAN",
    });
  });

  it("上游事实变化会使证据、分析、草稿和旧审计全部失效", () => {
    let state = createState();
    state = replaceEvidenceSnapshot(
      state,
      supporting("excavaguard.standard_evidence/v1", 1, "2", ["ev-1"]),
      BEFORE_DEADLINE,
    );
    state = replaceAnalysisSnapshot(
      state,
      supporting("excavaguard.analysis/v1", 1, "3", ["ev-1"]),
      BEFORE_DEADLINE,
    );
    const draft = draftFor(state, 1, "d");
    state = recordReportDraft(state, draft, BEFORE_DEADLINE);
    state = recordAuditResult(state, auditFor(draft, true), BEFORE_DEADLINE);

    const next = replaceEngineSnapshot(
      state,
      envelope("excavaguard.daily_report_input/v1", 2, "4"),
      BEFORE_DEADLINE,
    );

    expect(next.evidence_snapshot).toBeNull();
    expect(next.analysis_snapshot).toBeNull();
    expect(next.report_draft).toBeNull();
    expect(next.audit_result).toBeNull();
    expect(next.run.revision_count).toBe(0);
    expect(next.trace.at(-1)).toMatchObject({
      status: "invalidated",
      return_reason: "ENGINE_SNAPSHOT_CHANGED",
    });
  });

  it("修改草稿后旧审计不能重新写回", () => {
    let state = createState();
    const firstDraft = draftFor(state, 1, "d");
    state = recordReportDraft(state, firstDraft, BEFORE_DEADLINE);
    state = recordAuditResult(
      state,
      auditFor(firstDraft, false, "report-delivery"),
      BEFORE_DEADLINE,
    );

    const revisedDraft = draftFor(state, 2, "e");
    state = recordReportDraft(state, revisedDraft, BEFORE_DEADLINE);

    expect(state.audit_result).toBeNull();
    expect(() =>
      recordAuditResult(state, auditFor(firstDraft, true), BEFORE_DEADLINE),
    ).toThrowError("审计结果对应的草稿已失效");
  });

  it("时间预算和模型调用预算都能终止自动流程", () => {
    const state = createState(2, 0);
    expect(decideNextAction(state, AVAILABLE, AFTER_DEADLINE)).toMatchObject({
      type: "handoff_to_human",
      reason_code: "DEADLINE_EXCEEDED",
    });

    const modelCapabilities: AgentCapabilities = {
      ...AVAILABLE,
      render_report: { available: true, requires_model: true, reason_code: null },
    };
    expect(
      decideNextAction(state, modelCapabilities, BEFORE_DEADLINE),
    ).toMatchObject({
      type: "handoff_to_human",
      reason_code: "MODEL_CALL_BUDGET_EXHAUSTED",
    });
  });

  it("能力异常只记录失败轨迹，不创建成功产物", () => {
    const state = recordCapabilityFailure(createState(), {
      agent: "report-delivery",
      capability: "render-daily-report",
      code: "MODEL_NOT_CONFIGURED",
      message: "模型配置缺失。",
      at: BEFORE_DEADLINE,
    });

    expect(state.report_draft).toBeNull();
    expect(state.trace.at(-1)).toMatchObject({
      status: "failed",
      error: { code: "MODEL_NOT_CONFIGURED" },
      return_reason: "CAPABILITY_UNAVAILABLE",
    });
  });

  it("拒绝绕过状态机覆盖草稿、审计或调用预算", () => {
    let state = createState(2, 1);
    const firstDraft = draftFor(state, 1, "d");
    state = recordReportDraft(state, firstDraft, BEFORE_DEADLINE);

    expect(() =>
      recordReportDraft(state, draftFor(state, 2, "e"), BEFORE_DEADLINE),
    ).toThrowError("只有未通过审计的草稿可以进入自动修订");

    state = recordAuditResult(state, auditFor(firstDraft, true), BEFORE_DEADLINE);
    expect(() =>
      recordAuditResult(state, auditFor(firstDraft, true, "report-delivery", 2), BEFORE_DEADLINE),
    ).toThrowError("只有尚未审计的当前草稿可以写入审计结果");
    expect(() => recordModelCall(state, BEFORE_DEADLINE)).toThrowError(
      "自动流程结束后不能继续发起模型调用",
    );

    const budgetedState = recordModelCall(createState(2, 1), BEFORE_DEADLINE);
    expect(() => recordModelCall(budgetedState, BEFORE_DEADLINE)).toThrowError(
      "模型调用预算已耗尽",
    );
    expect(() => decideNextAction(state, AVAILABLE, "not-a-date")).toThrowError(
      "决策时间必须是有效日期时间",
    );
  });
});
