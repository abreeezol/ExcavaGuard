import { randomUUID } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  AgentRunState,
  ArtifactEnvelope,
  AuditResult,
  ReportDraft,
  SupportingSnapshot,
} from "@/contracts/agent-runtime";
import { executeAgentRun } from "@/server/agents/executor";
import { buildReportModelContext, validateNarrativeGrounding } from "@/server/agents/report-model";
import type { ReportNarrative } from "@/contracts/ai-report";
import type { ReportModelRequest, ReportModelResponse } from "@/server/agents/report-model";
import type { StandardEvidenceSkillResult } from "@/server/skills/retrieve-standard-evidence/runner";

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

  it("从报告检查点只继续审计，且存储故障不被误判为报告能力异常", async () => {
    let checkpoint: AgentRunState | null = null;
    await expect(executeAgentRun({
      enginePayload: { schema: "excavaguard.daily_report_input/v1" }, createdAt: NOW,
    }, {
      now: () => new Date(NOW),
      render: async (input) => ({ draft: draftFor(input), trace: {} }),
      checkpoint: async ({ state }) => {
        checkpoint = state;
        if (state.report_draft) throw new Error("store interrupted");
      },
    })).rejects.toThrow("store interrupted");
    expect(checkpoint!.run.status).toBe("draft_ready");
    expect(checkpoint!.trace.every((event) => event.status !== "failed")).toBe(true);
    const resumed = await executeAgentRun({
      enginePayload: null, initialState: checkpoint!,
    }, {
      now: () => new Date(NOW),
      render: async () => { throw new Error("must not render again"); },
      validate: async ({ draft }) => ({ audit: auditFor(draft, true), trace: {} }),
    });
    expect(resumed.state.run.status).toBe("awaiting_human_review");
    expect(resumed.state.engine_snapshot).toEqual(checkpoint!.engine_snapshot);
    expect(resumed.state.report_draft).toEqual(checkpoint!.report_draft);
    expect(resumed.state.limits).toEqual(checkpoint!.limits);
  });

  it("续跑不重置原截止时间，已到期时不调用任何报告能力", async () => {
    const stopped = await executeAgentRun({
      enginePayload: { schema: "excavaguard.daily_report_input/v1" }, createdAt: NOW,
    }, {
      now: () => new Date(NOW),
      render: async () => { throw new Error("unavailable"); },
    });
    const resumed = await executeAgentRun({ enginePayload: null, initialState: stopped.state }, {
      now: () => new Date("2026-10-14T02:00:00Z"),
      render: async () => { throw new Error("must not call"); },
    });
    expect(resumed.terminalAction.reason_code).toBe("DEADLINE_EXCEEDED");
    expect(resumed.state.limits).toEqual(stopped.state.limits);
  });
});

const AI_INPUT = {
  schema: "excavaguard.daily_report_input/v1",
  project: { name: "测试工程" }, summary: { total: 1, overall_risk_level: "未知" },
  items: [{ point_id: "P-01", metric_name: "水平位移", risk_level: "未知", cumulative: 3,
    abstain: ["MISSING_H"], abstain_reasons: ["缺设计深度"], checks: [] }],
};
const paragraph = (text = "请工程师补充设计资料并复核。") => ({ text, evidence_ids: [] as string[] });
function narrativeFor(text?: string): ReportNarrative {
  return {
    work_condition: paragraph("施工日志未提供，工况信息不足。"),
    analysis: [paragraph(text ?? "{{fact:items.0.point_id}} 判定为 {{fact:items.0.risk_level}}，不能视为安全。")],
    recommendations: [paragraph()], limitations: [paragraph("缺少设计深度，判据无法完整换算。")],
    appendix_analysis: [{ form: "A", analysis: paragraph(), recommendation: paragraph() }],
  };
}
const NO_HITS: StandardEvidenceSkillResult = {
  status: "abstained", code: "EVIDENCE_NOT_FOUND", message: "无匹配条文", evidence: [], notice: "测试",
  trace: { provider: "pinecone", query: "测试查询", filters: { effective_status: "active" }, limit: 3, hit_count: 0, evidence_ids: [] },
};
function aiDependencies() {
  const calls: ReportModelRequest[] = [];
  return {
    calls, now: () => new Date(NOW),
    retrieve: async () => NO_HITS,
    model: async (request: ReportModelRequest): Promise<ReportModelResponse> => {
      calls.push(request);
      const context = request.context as { evidence_topics: string[] };
      return {
        object: request.role === "supervisor"
          ? { focus_indices: [0], evidence_topics: context.evidence_topics }
          : request.role === "audit" ? { issues: [] } : narrativeFor(),
        model: "simulated-test-model", usage: { input_tokens: 10, output_tokens: 20 },
      };
    },
    render: async (request: Parameters<typeof draftFor>[0]) => ({ draft: draftFor(request), trace: {} }),
    validate: async ({ draft }: { draft: ReportDraft }) => ({ audit: auditFor(draft, true), trace: {} }),
  };
}

describe("实际模型接口编排与失败保护（模拟响应）", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("三个角色独立请求，无命中保留缺口且不改变未知事实", async () => {
    const dependencies = aiDependencies();
    const result = await executeAgentRun({ enginePayload: AI_INPUT, reportMode: "ai", createdAt: NOW }, dependencies);
    expect(dependencies.calls.map((call) => call.role)).toEqual(["supervisor", "report-delivery", "audit"]);
    expect(result.state.limits.model_calls_used).toBe(3);
    expect(result.state.evidence_snapshot).toMatchObject({ status: "insufficient", evidence_ids: [] });
    expect(result.state.evidence_snapshot?.gaps.length).toBe(2);
    expect(result.state.audit_result?.checks.at(-1)?.name).toBe("independent-llm-semantic-audit");
    expect(result.state.engine_snapshot.payload).toEqual(AI_INPUT);
    expect(result.terminalAction.reason_code).toBe("AUDIT_PASSED");
  });

  it("语义审计问题反馈给下一次写作，两轮仍不通过时保留阻断", async () => {
    const dependencies = aiDependencies();
    const model = dependencies.model;
    dependencies.model = async (request) => {
      const response = await model(request);
      if (request.role === "audit") response.object = { issues: [
        { code: "UNSUPPORTED_CLAIM", responsibility: "report-delivery", path: "analysis.0", message: "待修改的文字问题" },
      ] };
      return response;
    };
    const result = await executeAgentRun({ enginePayload: AI_INPUT, reportMode: "ai", createdAt: NOW }, dependencies);
    expect(result.state.limits.model_calls_used).toBe(7);
    expect(result.state.run.revision_count).toBe(2);
    expect(result.state.audit_result?.valid).toBe(false);
    const revisions = dependencies.calls.filter((call) => call.role === "report-delivery").slice(1);
    expect(revisions.every((call) => (call.context as { previous_issues: unknown[] }).previous_issues.length > 0)).toBe(true);
    expect(result.terminalAction.reason_code).toBe("REVISION_LIMIT_REACHED");
  });

  it("上游语义问题交工程师，不让报告 Agent 修改源事实", async () => {
    const dependencies = aiDependencies();
    const model = dependencies.model;
    dependencies.model = async (request) => {
      const response = await model(request);
      if (request.role === "audit") response.object = { issues: [
        { code: "EVIDENCE_CONFLICT", responsibility: "supervisor", path: "evidence", message: "证据适用性待核实" },
      ] };
      return response;
    };
    const result = await executeAgentRun({ enginePayload: AI_INPUT, reportMode: "ai", createdAt: NOW }, dependencies);
    expect(result.terminalAction.reason_code).toBe("UPSTREAM_ISSUE_REQUIRES_HUMAN");
    expect(result.state.run.revision_count).toBe(0);
  });

  it("缺少 LLM 配置时保留计算结果，没有模板回退或伪造调用", async () => {
    vi.stubEnv("LLM_API_KEY", "");
    const result = await executeAgentRun({ enginePayload: AI_INPUT, reportMode: "ai", createdAt: NOW }, { now: () => new Date(NOW) });
    expect(result.terminalAction.type).toBe("wait_for_capability");
    expect(result.state.report_draft).toBeNull();
    expect(result.state.limits.model_calls_used).toBe(0);
    expect(result.state.engine_snapshot.payload).toEqual(AI_INPUT);
  });

  it("请求失败计入预算，检查点在请求之前保存，续跑不重置预算", async () => {
    const dependencies = aiDependencies();
    let savedCalls = 0;
    dependencies.model = async () => {
      expect(savedCalls).toBe(1);
      throw new Error("test-only-secret-canary");
    };
    const failed = await executeAgentRun({ enginePayload: AI_INPUT, reportMode: "ai", createdAt: NOW }, {
      ...dependencies, checkpoint: async ({ state }) => { savedCalls = state.limits.model_calls_used; },
    });
    expect(failed.state.limits.model_calls_used).toBe(1);
    expect(JSON.stringify(failed)).not.toContain("test-only-secret-canary");
    const resumed = await executeAgentRun({ enginePayload: null, initialState: failed.state }, aiDependencies());
    expect(resumed.state.limits.model_calls_used).toBe(4);
    expect(resumed.state.limits.deadline_at).toBe(failed.state.limits.deadline_at);
  });

  it("检索服务不可用时停止交付，不能以无命中掩盖连接失败", async () => {
    const dependencies = aiDependencies();
    const result = await executeAgentRun({ enginePayload: AI_INPUT, reportMode: "ai", createdAt: NOW }, {
      ...dependencies,
      retrieve: async () => ({ ...NO_HITS, status: "abstained", code: "EVIDENCE_UNAVAILABLE" }),
    });
    expect(result.terminalAction.type).toBe("wait_for_capability");
    expect(result.state.report_draft).toBeNull();
    expect(dependencies.calls).toHaveLength(1);
  });

  it("AI 检查点保存失败直接报错，不发起模型请求或记录虚假能力故障", async () => {
    const dependencies = aiDependencies();
    let checkpointCount = 0;
    await expect(executeAgentRun({ enginePayload: AI_INPUT, reportMode: "ai", createdAt: NOW }, {
      ...dependencies,
      checkpoint: async () => {
        checkpointCount += 1;
        if (checkpointCount === 2) throw new Error("checkpoint unavailable");
      },
    })).rejects.toThrow("checkpoint unavailable");
    expect(dependencies.calls).toEqual([]);
  });

  it("检查点写入消耗剩余时间后停止，不以过期时间预算发起模型请求", async () => {
    const dependencies = aiDependencies();
    let at = new Date(NOW);
    const result = await executeAgentRun({
      enginePayload: AI_INPUT, reportMode: "ai", createdAt: NOW, timeoutMs: 1000,
    }, {
      ...dependencies, now: () => at,
      checkpoint: async ({ state }) => {
        if (state.limits.model_calls_used) at = new Date(Date.parse(NOW) + 1001);
      },
    });
    expect(dependencies.calls).toEqual([]);
    expect(result.terminalAction.reason_code).toBe("DEADLINE_EXCEEDED");
    expect(result.terminalAction.type).toBe("handoff_to_human");
    expect(result.state.report_draft).toBeNull();
  });

  it("从已冻结的正文续跑只渲染和审计，不重复规划、检索或写作", async () => {
    const dependencies = aiDependencies();
    let saved: AgentRunState | null = null;
    await expect(executeAgentRun({ enginePayload: AI_INPUT, reportMode: "ai", createdAt: NOW }, {
      ...dependencies,
      checkpoint: async ({ state }) => {
        if (state.analysis_snapshot) {
          saved = state;
          throw new Error("storage interrupted after narrative");
        }
      },
    })).rejects.toThrow("storage interrupted after narrative");
    expect(dependencies.calls.map((call) => call.role)).toEqual(["supervisor", "report-delivery"]);
    const resumedDependencies = aiDependencies();
    resumedDependencies.retrieve = async () => { throw new Error("must reuse evidence"); };
    const resumed = await executeAgentRun({ enginePayload: null, initialState: saved! }, resumedDependencies);
    expect(resumedDependencies.calls.map((call) => call.role)).toEqual(["audit"]);
    expect(resumed.state.limits.model_calls_used).toBe(3);
    expect(resumed.state.analysis_snapshot).toEqual(saved!.analysis_snapshot);
    expect(resumed.terminalAction.reason_code).toBe("AUDIT_PASSED");
  });

  it("预算耗尽的 AI 运行不重新发起准备调用", async () => {
    const dependencies = aiDependencies();
    const failed = await executeAgentRun({ enginePayload: AI_INPUT, reportMode: "ai", createdAt: NOW }, {
      ...dependencies, model: async () => { throw new Error("unavailable"); },
    });
    const state = { ...failed.state, limits: { ...failed.state.limits, max_model_calls: 1 } };
    const resumed = await executeAgentRun({ enginePayload: null, initialState: state }, dependencies);
    expect(dependencies.calls).toEqual([]);
    expect(resumed.terminalAction.reason_code).toBe("MODEL_CALL_BUDGET_EXHAUSTED");
  });

  it("非法事实、数字、引用、责任措辞和附表分析均阻断", () => {
    const context = buildReportModelContext(AI_INPUT);
    for (const text of ["{{fact:items.99.current}}", "实测值是 999。", "已正式签发", "{{坏占位符}}"]) {
      expect(() => validateNarrativeGrounding(narrativeFor(text), context.facts, [], context.forms)).toThrow();
    }
    const badCitation = narrativeFor();
    badCitation.analysis[0].evidence_ids = ["missing-evidence"];
    expect(() => validateNarrativeGrounding(badCitation, context.facts, [], context.forms)).toThrow("UNGROUNDED_CITATION");
    const missingForm = narrativeFor();
    missingForm.appendix_analysis = [];
    expect(() => validateNarrativeGrounding(missingForm, context.facts, [], context.forms)).toThrow("APPENDIX_ANALYSIS_MISMATCH");
  });
});
