import { randomUUID } from "node:crypto";
import { describe, expect, it } from "vitest";
import type {
  ArtifactEnvelope,
  AuditResult,
  ReportDraft,
  SupportingSnapshot,
} from "@/contracts/agent-runtime";
import { executeAgentRun } from "@/server/agents/executor";

const NOW = "2026-10-14T01:00:00.000Z";

function draftFor(request: {
  engineSnapshot: ArtifactEnvelope;
  evidenceSnapshot?: SupportingSnapshot | null;
  analysisSnapshot?: SupportingSnapshot | null;
  version?: number;
}): ReportDraft {
  const artifactId = randomUUID();
  const root = `var/report-artifacts/${artifactId}`;
  const version = request.version ?? 1;
  return {
    ref: {
      artifact_id: artifactId,
      schema: "excavaguard.report_draft/v1",
      version,
      content_hash: String(version).repeat(64).slice(0, 64),
    },
    source_refs: {
      engine: request.engineSnapshot.ref,
      evidence: request.evidenceSnapshot?.artifact?.ref ?? null,
      analysis: request.analysisSnapshot?.artifact?.ref ?? null,
    },
    fact_bindings: [],
    artifacts: [
      {
        kind: "workbook",
        file_name: "report.xlsx",
        relative_path: `${root}/report.xlsx`,
        media_type:
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        sha256: "a".repeat(64),
        size_bytes: 1,
        sheets: ["监测日报"],
      },
      {
        kind: "cover_markdown",
        file_name: "cover.md",
        relative_path: `${root}/cover.md`,
        media_type: "text/markdown; charset=utf-8",
        sha256: "b".repeat(64),
        size_bytes: 1,
        sheets: [],
      },
      {
        kind: "appendices_markdown",
        file_name: "appendices.md",
        relative_path: `${root}/appendices.md`,
        media_type: "text/markdown; charset=utf-8",
        sha256: "c".repeat(64),
        size_bytes: 1,
        sheets: [],
      },
    ],
    artifact_bindings: [],
    citations: [],
    review_required: true,
    payload: { status: "draft", version },
  };
}

function auditFor(draft: ReportDraft, valid: boolean): AuditResult {
  return {
    ref: {
      artifact_id: randomUUID(),
      schema: "excavaguard.audit_result/v1",
      version: draft.ref.version,
      content_hash: valid ? "d".repeat(64) : "e".repeat(64),
    },
    draft_ref: draft.ref,
    valid,
    checks: [{ name: "test-audit", valid }],
    issues: valid
      ? []
      : [
          {
            issue_id: `issue-${draft.ref.version}`,
            code: "REPORT_CONTENT_MISMATCH",
            severity: "error",
            blocking: true,
            responsibility: "report-delivery",
            path: "payload",
            message: "测试报告责任问题。",
          },
        ],
  };
}

describe("三 Agent 同步执行器", () => {
  it("按 Supervisor 动作完成报告、审计并停在人工复核", async () => {
    const result = await executeAgentRun(
      {
        enginePayload: { schema: "excavaguard.daily_report_input/v1" },
        createdAt: NOW,
      },
      {
        now: () => new Date(NOW),
        render: async (request) => ({
          draft: draftFor(request),
          trace: {},
        }),
        validate: async ({ draft }) => ({
          audit: auditFor(draft, true),
          trace: {},
        }),
      },
    );

    expect(result.steps).toBe(3);
    expect(result.state.run.status).toBe("awaiting_human_review");
    expect(result.state.report_draft?.ref.version).toBe(1);
    expect(result.state.audit_result?.valid).toBe(true);
    expect(result.terminalAction).toMatchObject({
      type: "handoff_to_human",
      reason_code: "AUDIT_PASSED",
    });
  });

  it("报告责任问题最多重渲染两轮后转人工", async () => {
    let renderCalls = 0;
    let validateCalls = 0;
    const result = await executeAgentRun(
      {
        enginePayload: { schema: "excavaguard.daily_report_input/v1" },
        createdAt: NOW,
        maxRevisionRounds: 2,
      },
      {
        now: () => new Date(NOW),
        render: async (request) => {
          renderCalls += 1;
          return { draft: draftFor(request), trace: {} };
        },
        validate: async ({ draft }) => {
          validateCalls += 1;
          return { audit: auditFor(draft, false), trace: {} };
        },
      },
    );

    expect(renderCalls).toBe(3);
    expect(validateCalls).toBe(3);
    expect(result.steps).toBe(7);
    expect(result.state.run.revision_count).toBe(2);
    expect(result.state.run.status).toBe("revision_required");
    expect(result.terminalAction).toMatchObject({
      type: "handoff_to_human",
      reason_code: "REVISION_LIMIT_REACHED",
    });
  });

  it("能力异常只留失败轨迹并停止，不伪造草稿", async () => {
    const result = await executeAgentRun(
      {
        enginePayload: { schema: "excavaguard.daily_report_input/v1" },
        createdAt: NOW,
      },
      {
        now: () => new Date(NOW),
        render: async () => {
          throw new Error("renderer unavailable");
        },
      },
    );

    expect(result.steps).toBe(1);
    expect(result.state.report_draft).toBeNull();
    expect(result.state.trace.at(-1)).toMatchObject({
      status: "failed",
      capability: "render-daily-report",
    });
    expect(result.terminalAction).toMatchObject({
      type: "wait_for_capability",
      reason_code: "CAPABILITY_UNAVAILABLE",
    });
  });
});
