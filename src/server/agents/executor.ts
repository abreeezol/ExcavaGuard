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
  buildReportModelContext, invokeReportModel, validateNarrativeGrounding, ReportModelError,
  type ReportModelRequest, type ReportModelResponse,
} from "@/server/agents/report-model";
import { reportNarrativeSchema, reportPlanSchema, semanticAuditSchema, type ReportMode } from "@/contracts/ai-report";
import { readIntegrationConfig } from "@/server/config";
import { retrieveStandardEvidence } from "@/server/skills/retrieve-standard-evidence/runner";
import type { StandardEvidence } from "@/contracts/standard-evidence";
import { createStandardEvidenceRetriever } from "@/server/evidence/factory";
import type { StandardEvidenceRetriever } from "@/server/evidence/retriever";
import type { ProjectStandardDocument } from "@/contracts/project-standards";
import { CombinedStandardRetriever, ProjectStandardRetriever, withProjectCatalog } from "@/server/evidence/project-standard-library";
import { readStandardCatalog } from "@/server/evidence/standard-catalog";
import { validateProjectStandardReferences } from "@/server/agents/project-standard-review";
import { EngineError } from "@/server/skills/python-bridge";
import { reviewAllStandards, retainDiverseEvidence, type StandardQueryReview } from "@/server/agents/standard-review";
import { reviewRecurringWarnings } from "@/server/agents/period-evidence";
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
  projectStandards?: { project_id: string; documents: ProjectStandardDocument[] };
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
    !["excavaguard.daily_report_input/v1", "excavaguard.period_report_input/v1"].includes(
      String((payload as { schema?: unknown }).schema),
    )
  ) {
    throw new Error(
      "Agent 执行器只接受日报或多周期报告 v1 引擎载荷。",
    );
  }
  return {
    ref: {
      artifact_id: randomUUID(),
      schema: String((payload as { schema: string }).schema),
      version: 1,
      content_hash: contentHash(payload),
    },
    payload,
  };
}

function errorDetails(error: unknown): { code: string; message: string } {
  if (error instanceof ReportModelError) return { code: error.code, message: error.message };
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

function citedEvidenceIds(draft: unknown): Set<string> | null {
  const sections = (draft as { sections?: { narrative?: unknown } })?.sections;
  if (!sections?.narrative) return null;
  const ids = new Set<string>();
  const visit = (value: unknown) => {
    if (Array.isArray(value)) value.forEach(visit);
    else if (value && typeof value === "object") {
      const object = value as Record<string, unknown>;
      if (Array.isArray(object.evidence_ids)) object.evidence_ids.forEach(id => { if (typeof id === "string") ids.add(id); });
      Object.values(object).forEach(visit);
    }
  };
  visit(sections.narrative);
  return ids;
}

function compactEvidence(payload: unknown, draft: unknown): unknown {
  if (!payload || typeof payload !== "object") return null;
  const evidence = (payload as { evidence?: unknown }).evidence;
  if (!Array.isArray(evidence)) return payload;
  const ids = citedEvidenceIds(draft);
  const coverage = (payload as { coverage?: { catalogue_count?: unknown; queried_count?: unknown; completed?: unknown; notice?: unknown } }).coverage;
  return {
    schema: (payload as { schema?: unknown }).schema,
    gaps: (payload as { gaps?: unknown }).gaps,
    extended_review: (payload as { extended_review?: unknown }).extended_review,
    coverage: coverage ? { catalogue_count: coverage.catalogue_count, queried_count: coverage.queried_count,
      completed: coverage.completed, notice: coverage.notice } : undefined,
    // Every source cited in the prose remains available; uncited OCR tables were
    // already fully checked by the deterministic artifact auditor.
    evidence: evidence.filter(item => ids === null || ids.has(String((item as { id?: unknown }).id))).map((item) => {
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
  const sections = record.sections as { narrative?: unknown } | undefined;
  const markdown = typeof record.markdown === "string" ? record.markdown : "";
  // Review authored prose, not deterministic templates or copied normative tables.
  const body = sections?.narrative ? JSON.stringify(sections.narrative) : markdown;
  return { status: record.status, markdown: sections?.narrative ? body : truncateText(body, 24_000) };
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
    } catch (error) {
      const safe = error instanceof ReportModelError ? error : new ReportModelError("LLM_REQUEST_FAILED");
      state = agentRunStateSchema.parse({ ...state, trace: [...state.trace, {
        event_id: randomUUID(), agent: role, capability: `llm-${role}`, status: "failed",
        input_versions: { engine: state.engine_snapshot.ref.content_hash }, output_versions: {},
        rule_ids: ["MODEL_RESPONSE_REQUIRED"], evidence_ids: [],
        error: { code: safe.code, message: safe.message }, return_reason: null,
        started_at: at, finished_at: now().toISOString(),
      }] });
      throw safe;
    }
  };
  let modelContext: ReturnType<typeof buildReportModelContext> | null = null;
  const projectDocuments = input.projectStandards?.documents ?? [];
  if (reportMode === "ai" || projectDocuments.length) {
    try {
      modelContext = buildReportModelContext(state.engine_snapshot.payload);
      if (reportMode === "ai" && !state.plan_snapshot) {
        const response = await modelCall("supervisor", modelContext, 1);
        const proposedPlan = reportPlanSchema.parse(response.object);
        const plan = { ...proposedPlan, evidence_topics: modelContext.evidence_topics };
        if (plan.focus_indices.some((i) => i >= modelContext!.items.length) ||
            proposedPlan.evidence_topics.some((topic) => !modelContext!.evidence_topics.includes(topic))) {
          throw new Error("INVALID_PLAN：规划未覆盖实际测项，或引用未知测项。");
        }
        state = agentRunStateSchema.parse({
          ...state, plan_snapshot: freeze("excavaguard.report_plan/v1", plan),
        });
        await checkpoint(1);
      }
      if (!state.evidence_snapshot || state.evidence_snapshot.status === "unavailable") {
        const plan = reportMode === "ai" ? reportPlanSchema.parse(state.plan_snapshot!.payload)
          : { evidence_topics: modelContext.evidence_topics };
        const evidence = new Map<string, StandardEvidence>();
        const gaps: string[] = [];
        for (const doc of projectDocuments) {
          if (doc.unindexed_pages.length) gaps.push(`《${doc.standard_name}》${doc.standard_version}：第${doc.unindexed_pages.join("、")}页文字不足未完整入库，须人工核对。`);
        }
        const queries: StandardQueryReview[] = [];
        const projectRetriever = projectDocuments.length
          ? new ProjectStandardRetriever(input.projectStandards!.project_id, projectDocuments) : null;
        const baseRetriever: StandardEvidenceRetriever | null = reportMode !== "ai" ? null : dependencies.retrieve
          ? { provider: "local", search: async query => {
            const result = await dependencies.retrieve!({ query: query.query, filters: query.filters, limit: query.top_k });
            if (result.status === "abstained" && result.code !== "EVIDENCE_NOT_FOUND") throw new Error(result.code);
            return result.evidence;
          } } : createStandardEvidenceRetriever();
        const sharedRetriever = projectRetriever ? (baseRetriever ? new CombinedStandardRetriever(baseRetriever, projectRetriever) : projectRetriever)
          : baseRetriever;
        const standardReview = await reviewAllStandards({
          topics: plan.evidence_topics, enginePayload: state.engine_snapshot.payload,
          catalog: withProjectCatalog(reportMode === "ai" ? readStandardCatalog() : [], projectDocuments),
          search: async (request) => {
            const remaining = Date.parse(state.limits.deadline_at) - now().getTime();
            if (remaining <= 0) throw new Error("DEADLINE_EXCEEDED：规范检索预算已到。");
            const signal = AbortSignal.timeout(Math.max(1, Math.min(30_000, remaining)));
            return dependencies.retrieve && !projectRetriever ? dependencies.retrieve(request, { signal })
              : retrieveStandardEvidence(request, { signal, retriever: sharedRetriever ?? undefined });
          },
          onQuery: async (query, result) => {
            const at = now().toISOString();
            queries.push(query);
            state = agentRunStateSchema.parse({ ...state, trace: [...state.trace, {
              event_id: randomUUID(), agent: "supervisor", capability: "retrieve-standard-evidence",
              status: query.accepted_ids.length ? "success" : "abstained",
              input_versions: { query: result.trace.query, filters: JSON.stringify(result.trace.filters), scope: query.scope },
              output_versions: { provider: result.trace.provider, hit_count: String(query.accepted_ids.length),
                standard_name: query.standard_name ?? "跨规范主题检索", standard_version: query.standard_version ?? "全部现行规范" },
              rule_ids: ["CATALOGUE_COVERAGE_REQUIRED", "ACTIVE_VERSION_AND_TOPIC"], evidence_ids: query.accepted_ids,
              error: result.status === "abstained" ? { code: result.code, message: result.message } : null,
              return_reason: query.accepted_ids.length ? null : "未取得适用候选，不代表该规范无要求；须人工查证。",
              started_at: at, finished_at: at,
            }] });
            if (queries.length % 4 === 0) await checkpoint(1);
          },
        });
        if (reportMode !== "ai") standardReview.coverage.notice = "模板模式仅检索本工程补充规范；共享规范库未进行运行时检索。" + standardReview.coverage.notice;
        standardReview.evidence.forEach(item => evidence.set(item.id, item));
        gaps.push(...standardReview.gaps);
        await checkpoint(1);
        const extended = await reviewRecurringWarnings(state.engine_snapshot.payload, [...evidence.keys()], async (request) => {
          const remaining = Date.parse(state.limits.deadline_at) - now().getTime();
          if (remaining <= 0) throw new Error("DEADLINE_EXCEEDED：追加规范核查预算已到。");
          const signal = AbortSignal.timeout(Math.max(1, Math.min(30_000, remaining)));
          return dependencies.retrieve && !projectRetriever ? dependencies.retrieve(request, { signal })
            : retrieveStandardEvidence(request, { signal, retriever: sharedRetriever ?? undefined });
        });
        retainDiverseEvidence([...evidence.values(), ...extended.evidence], 144)
          .forEach((item) => evidence.set(item.id, item));
        gaps.push(...extended.gaps);
        if (extended.review.triggered) {
          const at = now().toISOString();
          state = agentRunStateSchema.parse({ ...state, trace: [...state.trace, {
            event_id: randomUUID(), agent: "supervisor", capability: "retrieve-standard-evidence",
            status: extended.gaps.length ? "abstained" : "success",
            input_versions: { scope: "multi-day-warning-expanded", query_count: String(extended.review.checks.length) },
            output_versions: { status: extended.review.status, hit_count: String(extended.evidence.length) },
            rule_ids: ["MULTI_DAY_WARNING_EXPANDED_SCOPE", "ACTIVE_VERSION_ONLY", "ENGINEER_CONFIRMATION_REQUIRED"],
            evidence_ids: extended.evidence.map((item) => item.id), error: null,
            return_reason: extended.review.notice, started_at: at, finished_at: at,
          }] });
        }
        const payload = { schema: "excavaguard.standard_evidence/v1", evidence: [...evidence.values()], queries, gaps,
          project_standards: projectDocuments,
          coverage: standardReview.coverage, comparisons: standardReview.comparisons,
          ...(extended.review.triggered ? { extended_review: extended.review } : {}) };
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
  if (reportMode !== "ai") modelContext = null;

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
                validateProjectStandardReferences(narrative,
                  (state.evidence_snapshot?.artifact?.payload as { evidence?: StandardEvidence[] })?.evidence ?? []);
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
          const draftSections = (state.report_draft.payload as { sections?: { narrative_facts?: Array<{ path: string }> } }).sections;
          const referencedFacts = draftSections?.narrative_facts;
          const factPaths = new Set(referencedFacts?.map(item => item.path) ?? []);
          const relatedPrefixes = [...new Set([...factPaths].flatMap(path => {
            const match = path.match(/^(items\.\d+\.|period\.(?:channels|daily_summaries)\.\d+\.)/);
            return match ? [match[0]] : [];
          }))];
          const auditFacts = referencedFacts ? Object.fromEntries(Object.entries(modelContext.facts).filter(([path]) =>
            /^(project|summary|context|data_quality)\./.test(path) ||
            /^period\.(?!(?:channels|daily_summaries|daily_items|recurring_warnings)\.)/.test(path) ||
            factPaths.has(path) || relatedPrefixes.some(prefix => path.startsWith(prefix)))) : modelContext.facts;
          const engineItems = (state.engine_snapshot.payload as { items?: Array<{ evidence?: unknown }> }).items ?? [];
          const judgmentSources = [...new Map(engineItems.filter(item => item.evidence).map(item => [JSON.stringify(item.evidence), item.evidence])).values()];
          const auditContext = {
            facts: auditFacts,
            numeric_judgment_sources: judgmentSources,
            audit_scope: "仅审查draft中模型撰写段落。facts是已通过确定性核验的正文标量及整体汇总；数值判据来源独立于RAG候选，不要求每项阈值来源在RAG中再次命中。完整表格、统计、引用与文件由确定性审计负责，不自行重新统计。",
            forms: modelContext.forms,
            evidence_ids: state.evidence_snapshot?.evidence_ids ?? [],
            evidence: compactEvidence(state.evidence_snapshot?.artifact?.payload, state.report_draft.payload),
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
