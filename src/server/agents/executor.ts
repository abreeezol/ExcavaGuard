import "server-only";
import { createHash, randomUUID } from "node:crypto";
import {
  agentRunStateSchema,
  supervisorActionSchema,
  type AgentCapabilities,
  type AgentRunState,
  type ArtifactEnvelope,
  type SupportingSnapshot,
  type SupervisorAction,
} from "@/contracts/agent-runtime";
import {
  createAgentRunState,
  decideNextAction,
  recordAuditResult,
  recordCapabilityFailure,
  recordModelCall,
  recordReportDraft,
} from "@/server/agents/supervisor";
import {
  buildReportModelContext, invokeReportModel, validateNarrativeGrounding,
  type ReportModelRequest, type ReportModelResponse,
} from "@/server/agents/report-model";
import { reportNarrativeSchema, reportPlanSchema, semanticAuditSchema, type ReportMode } from "@/contracts/ai-report";
import { readIntegrationConfig } from "@/server/config";
import { retrieveStandardEvidence } from "@/server/skills/retrieve-standard-evidence/runner";
import type { StandardEvidence } from "@/contracts/standard-evidence";
import { createStandardEvidenceRetriever } from "@/server/evidence/factory";
import type { StandardEvidenceRetriever } from "@/server/evidence/retriever";
import { EngineError } from "@/server/skills/python-bridge";
import { renderDailyReport } from "@/server/skills/render-daily-report/runner";
import { validateReport } from "@/server/skills/validate-report/runner";

const DEFAULT_TIMEOUT_MS = 300_000;
const DEFAULT_MAX_REVISION_ROUNDS = 2;
const DEFAULT_MAX_EXECUTION_STEPS = 8;
const AUDIT_MODEL_RETRIES = 2;
class CheckpointError extends Error {}
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const CAPABILITIES: AgentCapabilities = {
  render_report: {
    available: true,
    requires_model: false,
    reason_code: null,
  },
  validate_report: {
    available: true,
    requires_model: false,
    reason_code: null,
  },
};

type ExecuteAgentRunInput = {
  enginePayload: unknown;
  evidenceSnapshot?: SupportingSnapshot | null;
  analysisSnapshot?: SupportingSnapshot | null;
  runId?: string;
  createdAt?: string;
  timeoutMs?: number;
  maxRevisionRounds?: number;
  templateVersion?: string;
  initialState?: AgentRunState;
  reportMode?: ReportMode;
};

type ExecutorDependencies = {
  render?: typeof renderDailyReport;
  validate?: typeof validateReport;
  now?: () => Date;
  checkpoint?: (execution: AgentRunExecutionResult) => Promise<void>;
  model?: (request: ReportModelRequest) => Promise<ReportModelResponse>;
  retrieve?: typeof retrieveStandardEvidence;
};

export type AgentRunExecutionResult = {
  state: AgentRunState;
  terminalAction: SupervisorAction;
  steps: number;
};

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, nested]) => [key, stableValue(nested)]),
    );
  }
  return value;
}

function contentHash(value: unknown): string {
  return createHash("sha256")
    .update(JSON.stringify(stableValue(value)))
    .digest("hex");
}

function engineSnapshot(payload: unknown): ArtifactEnvelope {
  if (
    !payload ||
    typeof payload !== "object" ||
    (payload as { schema?: unknown }).schema !==
      "excavaguard.daily_report_input/v1"
  ) {
    throw new Error(
      "Agent 执行器只接受 excavaguard.daily_report_input/v1 引擎载荷。",
    );
  }
  return {
    ref: {
      artifact_id: randomUUID(),
      schema: "excavaguard.daily_report_input/v1",
      version: 1,
      content_hash: contentHash(payload),
    },
    payload,
  };
}

function errorDetails(error: unknown): { code: string; message: string } {
  if (error instanceof EngineError) {
    return { code: error.engineCode, message: error.message };
  }
  if (error instanceof Error) {
    return {
      code:
        error.name && error.name !== "Error"
          ? error.name
          : "CAPABILITY_EXECUTION_FAILED",
      message: error.message,
    };
  }
  return {
    code: "CAPABILITY_EXECUTION_FAILED",
    message: String(error),
  };
}

function capabilityFailureAction(
  action: SupervisorAction,
  error: unknown,
): SupervisorAction {
  const details = errorDetails(error);
  return supervisorActionSchema.parse({
    type: "wait_for_capability",
    agent: action.agent,
    reason_code: "CAPABILITY_UNAVAILABLE",
    details: `${details.code}: ${details.message}`,
  });
}

function truncateText(value: unknown, limit: number): string {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? "");
  return text.length <= limit ? text : `${text.slice(0, limit)}\n...[truncated]`;
}

function compactEvidence(payload: unknown): unknown {
  if (!payload || typeof payload !== "object") return null;
  const evidence = (payload as { evidence?: unknown }).evidence;
  if (!Array.isArray(evidence)) return payload;
  return {
    schema: (payload as { schema?: unknown }).schema,
    gaps: (payload as { gaps?: unknown }).gaps,
    evidence: evidence.slice(0, 24).map((item) => {
      const record = item as {
        id?: unknown;
        text?: unknown;
        metadata?: {
          standard_name?: unknown;
          standard_version?: unknown;
          clause?: unknown;
          applicability?: unknown;
        };
      };
      return {
        id: record.id,
        text: truncateText(record.text, 800),
        metadata: {
          standard_name: record.metadata?.standard_name,
          standard_version: record.metadata?.standard_version,
          clause: record.metadata?.clause,
          applicability: record.metadata?.applicability,
        },
      };
    }),
  };
}

function compactDraftForSemanticAudit(draft: unknown): unknown {
  if (!draft || typeof draft !== "object") return draft;
  const record = draft as Record<string, unknown>;
  return {
    status: record.status,
    markdown: truncateText(record.markdown, 24_000),
  };
}

function recordTiming(state: AgentRunState, startedAt: string): AgentRunState {
  return agentRunStateSchema.parse({
    ...state,
    trace: state.trace.map((event, index) =>
      index === state.trace.length - 1 ? { ...event, started_at: startedAt } : event),
  });
}

export async function executeAgentRun(
  input: ExecuteAgentRunInput,
  dependencies: ExecutorDependencies = {},
): Promise<AgentRunExecutionResult> {
  const render = dependencies.render ?? renderDailyReport;
  const validate = dependencies.validate ?? validateReport;
  const now = dependencies.now ?? (() => new Date());
  const createdAt = input.createdAt ?? now().toISOString();
  const createdAtMs = Date.parse(createdAt);
  const reportMode = input.initialState?.report_mode ?? input.reportMode ?? "template";
  const capabilities: AgentCapabilities = reportMode === "ai" ? {
    render_report: { ...CAPABILITIES.render_report, requires_model: true },
    validate_report: { ...CAPABILITIES.validate_report, requires_model: true },
  } : CAPABILITIES;
  const timeoutMs = input.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  if (
    !Number.isFinite(createdAtMs) ||
    !Number.isInteger(timeoutMs) ||
    timeoutMs <= 0
  ) {
    throw new Error("Agent 执行器的创建时间或超时预算不合法。");
  }

  let state = input.initialState ? agentRunStateSchema.parse(input.initialState) : createAgentRunState({
    runId: input.runId ?? randomUUID(),
    createdAt,
    deadlineAt: new Date(createdAtMs + timeoutMs).toISOString(),
    maxModelCalls: reportMode === "ai" ? 7 : 0,
    maxRevisionRounds:
      input.maxRevisionRounds ?? DEFAULT_MAX_REVISION_ROUNDS,
    engineSnapshot: engineSnapshot(input.enginePayload),
    evidenceSnapshot: input.evidenceSnapshot ?? null,
    analysisSnapshot: input.analysisSnapshot ?? null,
  });
  state = agentRunStateSchema.parse({ ...state, report_mode: reportMode });
  if (state.human_review.decision !== null) {
    throw new Error("已提交人工决定的运行不可继续自动执行。");
  }
  const checkpoint = async (steps: number, terminalAction?: SupervisorAction) => {
    try {
      await dependencies.checkpoint?.({
        state,
        terminalAction: terminalAction ?? decideNextAction(state, capabilities, now().toISOString()),
        steps,
      });
    } catch (error) {
      throw new CheckpointError(error instanceof Error ? error.message : "检查点保存失败。", { cause: error });
    }
  };
  await checkpoint(1);
  const initialAction = decideNextAction(state, capabilities, now().toISOString());
  if (initialAction.type === "handoff_to_human") {
    return { state, terminalAction: initialAction, steps: 1 };
  }
  const freeze = (schema: string, payload: unknown, version = 1): ArtifactEnvelope => ({
    ref: { artifact_id: randomUUID(), schema, version, content_hash: contentHash(payload) }, payload,
  });
  const modelCall = async (role: ReportModelRequest["role"], context: unknown, steps: number) => {
    if (Date.parse(state.limits.deadline_at) <= now().getTime()) {
      throw new Error("DEADLINE_EXCEEDED：运行时间预算已到。");
    }
    if (!dependencies.model) readIntegrationConfig("llm");
    state = recordModelCall(state, now().toISOString());
    const at = now().toISOString();
    await checkpoint(steps);
    const remaining = Date.parse(state.limits.deadline_at) - now().getTime();
    if (remaining <= 0) throw new Error("DEADLINE_EXCEEDED：检查点保存后运行预算已到。");
    try {
      const response = await (dependencies.model ?? invokeReportModel)({
        role, context, timeoutMs: Math.min(45_000, remaining),
      });
      state = agentRunStateSchema.parse({
        ...state, trace: [...state.trace, {
          event_id: randomUUID(), agent: role, capability: `llm-${role}`,
          status: "success",
          input_versions: { engine: state.engine_snapshot.ref.content_hash },
          output_versions: {
            model: response.model, input_tokens: String(response.usage.input_tokens),
            output_tokens: String(response.usage.output_tokens),
            response_hash: contentHash(response.object),
          },
          rule_ids: ["FROZEN_FACTS_ONLY"], evidence_ids: state.evidence_snapshot?.evidence_ids ?? [],
          error: null, return_reason: null, started_at: at, finished_at: now().toISOString(),
        }],
      });
      return response;
    } catch {
      throw new Error("LLM_REQUEST_FAILED：模型调用失败，保留检查点等待处理。");
    }
  };
  let modelContext: ReturnType<typeof buildReportModelContext> | null = null;
  if (reportMode === "ai") {
    try {
      modelContext = buildReportModelContext(state.engine_snapshot.payload);
      if (!state.plan_snapshot) {
        const response = await modelCall("supervisor", modelContext, 1);
        const plan = reportPlanSchema.parse(response.object);
        if (plan.focus_indices.some((i) => i >= modelContext!.items.length) ||
            plan.evidence_topics.some((topic) => !modelContext!.evidence_topics.includes(topic)) ||
            modelContext.evidence_topics.some((topic) => !plan.evidence_topics.includes(topic))) {
          throw new Error("INVALID_PLAN：规划未覆盖实际测项，或引用未知测项。");
        }
        state = agentRunStateSchema.parse({
          ...state, plan_snapshot: freeze("excavaguard.report_plan/v1", plan),
        });
        await checkpoint(1);
      }
      if (!state.evidence_snapshot || state.evidence_snapshot.status === "unavailable") {
        const plan = reportPlanSchema.parse(state.plan_snapshot!.payload);
        const evidence = new Map<string, StandardEvidence>();
        const gaps: string[] = [];
        const queries = [];
        const sharedRetriever: StandardEvidenceRetriever | null = dependencies.retrieve
          ? null : createStandardEvidenceRetriever();
        for (const topic of [...new Set(plan.evidence_topics)]) {
          const at = now().toISOString();
          if (Date.parse(state.limits.deadline_at) <= Date.parse(at)) {
            throw new Error("DEADLINE_EXCEEDED：规范检索前运行预算已到。");
          }
          let result: Awaited<ReturnType<typeof retrieveStandardEvidence>> | null = null;
          for (let attempt = 0; attempt < 5; attempt++) {
            if (attempt > 0) await wait(1_000 * attempt);
            const request = {
              query: topic.includes("：")
                ? `GB 50497-2019 ${topic} 监测方法 精度 布点要求`
                : "GB 50497-2019 监测预警值应由基坑工程设计方确定",
              filters: { effective_status: "active", standard_versions: ["GB50497-2019"] },
              limit: 3,
            };
            const signal = AbortSignal.timeout(Math.max(1, Math.min(30_000, Date.parse(state.limits.deadline_at) - now().getTime())));
            result = dependencies.retrieve
              ? await dependencies.retrieve(request, { signal })
              : await retrieveStandardEvidence(request, { signal, retriever: sharedRetriever ?? undefined });
            if (!(result.status === "abstained" && result.code === "EVIDENCE_UNAVAILABLE")) break;
          }
          if (!result) throw new Error("EVIDENCE_UNAVAILABLE：规范检索服务暂不可用，停止 AI 报告交付。");
          const terms = topic.includes("：") ? topic.split("：")[1].split("、") : [];
          const accepted = result.status === "success" ? result.evidence.filter((item) =>
            item.metadata.effective_status === "active" && item.metadata.standard_version === "GB50497-2019" &&
            item.text.length <= 8000 && /应|宜|不得|必须/.test(item.text) && (
              terms.length ? terms.some((term) => item.text.includes(term))
                : /8[.．]0[.．]1/.test(item.metadata.clause) || item.text.includes("设计方")
            ),
          ) : [];
          accepted.forEach((item) => evidence.set(item.id, item));
          if (!accepted.length) gaps.push(`${topic}：未检索到主题匹配的现行条文，需人工补充核对。`);
          queries.push({ ...result.trace, topic, accepted_ids: accepted.map((item) => item.id) });
          state = agentRunStateSchema.parse({
            ...state, trace: [...state.trace, {
              event_id: randomUUID(), agent: "supervisor", capability: "retrieve-standard-evidence",
              status: accepted.length ? "success" : "abstained",
              input_versions: { query: result.trace.query, filters: JSON.stringify(result.trace.filters) },
              output_versions: { provider: result.trace.provider, hit_count: String(accepted.length) },
              rule_ids: ["ACTIVE_VERSION_AND_TOPIC"], evidence_ids: accepted.map((item) => item.id),
              error: result.status === "abstained" ? { code: result.code, message: result.message } : null,
              return_reason: accepted.length ? null : gaps.at(-1)!, started_at: at, finished_at: now().toISOString(),
            }],
          });
          await checkpoint(1);
          if (result.status === "abstained" && result.code === "EVIDENCE_UNAVAILABLE") {
            throw new Error("EVIDENCE_UNAVAILABLE：规范检索服务暂不可用，停止 AI 报告交付。");
          }
        }
        const payload = { schema: "excavaguard.standard_evidence/v1", evidence: [...evidence.values()], queries, gaps };
        state = agentRunStateSchema.parse({
          ...state, evidence_snapshot: {
            status: evidence.size ? "ready" : "insufficient", artifact: freeze(payload.schema, payload),
            evidence_ids: [...evidence.keys()], gaps,
          },
        });
        await checkpoint(1);
      }
    } catch (error) {
      if (error instanceof CheckpointError) throw error;
      state = recordCapabilityFailure(state, {
        agent: "supervisor", capability: "prepare-ai-report", ...errorDetails(error), at: now().toISOString(),
      });
      const nextAction = decideNextAction(state, capabilities, now().toISOString());
      const terminalAction = nextAction.type === "handoff_to_human" ? nextAction : capabilityFailureAction({
        type: "render_report", agent: "supervisor", reason_code: "READY_TO_RENDER", details: "准备 AI 报告",
      }, error);
      await checkpoint(1, terminalAction);
      return { state, terminalAction, steps: 1 };
    }
  }

  for (let steps = 1; steps <= DEFAULT_MAX_EXECUTION_STEPS; steps += 1) {
    const at = now().toISOString();
    const action = decideNextAction(state, capabilities, at);
    state = agentRunStateSchema.parse({
      ...state,
      trace: [...state.trace, {
        event_id: randomUUID(), agent: "supervisor", capability: "route-agent",
        status: action.type === "wait_for_capability" ? "abstained" : "success",
        input_versions: { engine: `${state.engine_snapshot.ref.artifact_id}@${state.engine_snapshot.ref.version}` },
        output_versions: { action: action.type, agent: action.agent },
        rule_ids: [action.reason_code], evidence_ids: state.evidence_snapshot?.evidence_ids ?? [],
        error: null, return_reason: action.details, started_at: at, finished_at: at,
      }],
    });

    if (action.type === "render_report" || action.type === "revise_report") {
      try {
        const version = (state.report_draft?.ref.version ?? 0) + 1;
        if (modelContext) {
          const cached = state.analysis_snapshot?.artifact?.payload as { draft_version?: number } | undefined;
          if (cached?.draft_version !== version) {
            let response: ReportModelResponse | null = null;
            let narrative = null;
            let previousIssues: unknown[] = state.audit_result?.issues ?? [];
            for (let attempt = 0; attempt < 2; attempt++) {
              response = await modelCall("report-delivery", {
                ...modelContext, plan: state.plan_snapshot?.payload,
                evidence: state.evidence_snapshot?.artifact?.payload,
                previous_issues: previousIssues,
              }, steps);
              narrative = reportNarrativeSchema.parse(response.object);
              try {
                validateNarrativeGrounding(narrative, modelContext.facts, state.evidence_snapshot?.evidence_ids ?? [], modelContext.forms);
                break;
              } catch (error) {
                if (attempt === 1) throw error;
                previousIssues = [{
                  code: "UNGROUNDED_FACT",
                  path: "report_narrative",
                  message: error instanceof Error ? error.message : "正文存在未绑定事实。",
                }];
              }
            }
            if (!response || !narrative) throw new Error("LLM_REQUEST_FAILED：模型未生成可审计正文。");
            const payload = { schema: "excavaguard.report_narrative/v1", narrative, draft_version: version, model: response.model };
            state = agentRunStateSchema.parse({
              ...state, analysis_snapshot: {
                status: "ready", artifact: freeze(payload.schema, payload, version),
                evidence_ids: state.evidence_snapshot?.evidence_ids ?? [], gaps: [],
              },
            });
            await checkpoint(steps);
          }
        }
        const { draft } = await render({
          engineSnapshot: state.engine_snapshot,
          evidenceSnapshot: state.evidence_snapshot,
          analysisSnapshot: state.analysis_snapshot,
          templateVersion: input.templateVersion,
          version,
        });
        state = recordReportDraft(state, draft, now().toISOString());
        state = recordTiming(state, at);
      } catch (error) {
        if (error instanceof CheckpointError) throw error;
        const details = errorDetails(error);
        state = recordCapabilityFailure(state, {
          agent: "report-delivery",
          capability: "render-daily-report",
          ...details,
          at: now().toISOString(),
        });
        state = recordTiming(state, at);
        const nextAction = decideNextAction(state, capabilities, now().toISOString());
        const terminalAction = nextAction.type === "handoff_to_human" ? nextAction : capabilityFailureAction(action, error);
        await checkpoint(steps, terminalAction);
        return { state, terminalAction, steps };
      }
      await checkpoint(steps);
      continue;
    }

    if (action.type === "audit_report") {
      try {
        if (!state.report_draft) {
          throw new Error("Supervisor 请求审计时没有当前报告草稿。");
        }
        const { audit: deterministicAudit } = await validate({
          draft: state.report_draft,
          engineSnapshot: state.engine_snapshot,
          evidenceSnapshot: state.evidence_snapshot,
          analysisSnapshot: state.analysis_snapshot,
          templateVersion: input.templateVersion,
          version: state.report_draft.ref.version,
        });
        let audit = deterministicAudit;
        if (modelContext && deterministicAudit.valid) {
          const auditContext = {
            facts: modelContext.facts,
            forms: modelContext.forms,
            evidence_ids: state.evidence_snapshot?.evidence_ids ?? [],
            evidence: compactEvidence(state.evidence_snapshot?.artifact?.payload),
            draft: compactDraftForSemanticAudit(state.report_draft.payload),
            deterministic_checks: deterministicAudit.checks,
          };
          let response: ReportModelResponse | null = null;
          let lastError: unknown = null;
          for (let attempt = 0; attempt < AUDIT_MODEL_RETRIES; attempt += 1) {
            try {
              response = await modelCall("audit", auditContext, steps);
              break;
            } catch (error) {
              lastError = error;
              if (attempt + 1 < AUDIT_MODEL_RETRIES) await wait(1_000);
            }
          }
          if (response) {
            const semantic = semanticAuditSchema.parse(response.object);
            const issues = [...deterministicAudit.issues, ...semantic.issues.map((issue, index) => ({
              ...issue, issue_id: `semantic-${state.report_draft!.ref.version}-${index + 1}`,
              severity: "error" as const, blocking: true,
            }))];
            audit = {
              ...deterministicAudit,
              ref: freeze("excavaguard.audit_result/v1", { deterministicAudit, semantic }, state.report_draft.ref.version).ref,
              valid: !issues.some((issue) => issue.blocking),
              issues,
              checks: [...deterministicAudit.checks, { name: "independent-llm-semantic-audit", valid: !semantic.issues.length }],
            };
          } else {
            audit = {
              ...deterministicAudit,
              ref: freeze("excavaguard.audit_result/v1", { deterministicAudit, semantic: null, semantic_error: errorDetails(lastError) }, state.report_draft.ref.version).ref,
              checks: [...deterministicAudit.checks, {
                name: "independent-llm-semantic-audit",
                valid: true,
                details: "LLM 语义审查暂不可用；已通过确定性文件、事实、引用和责任措辞审计，进入人工复核。",
              }],
            };
          }
        }
        state = recordAuditResult(state, audit, now().toISOString());
        state = recordTiming(state, at);
      } catch (error) {
        if (error instanceof CheckpointError) throw error;
        const details = errorDetails(error);
        state = recordCapabilityFailure(state, {
          agent: "audit",
          capability: "validate-report",
          ...details,
          at: now().toISOString(),
        });
        state = recordTiming(state, at);
        const nextAction = decideNextAction(state, capabilities, now().toISOString());
        const terminalAction = nextAction.type === "handoff_to_human" ? nextAction : capabilityFailureAction(action, error);
        await checkpoint(steps, terminalAction);
        return { state, terminalAction, steps };
      }
      await checkpoint(steps);
      continue;
    }

    return { state, terminalAction: action, steps };
  }

  return {
    state,
    terminalAction: supervisorActionSchema.parse({
      type: "handoff_to_human",
      agent: "supervisor",
      reason_code: "REVISION_LIMIT_REACHED",
      details: "执行步数达到保护上限，停止自动处理并转工程师复核。",
    }),
    steps: DEFAULT_MAX_EXECUTION_STEPS,
  };
}
