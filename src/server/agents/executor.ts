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
  recordReportDraft,
} from "@/server/agents/supervisor";
import { EngineError } from "@/server/skills/python-bridge";
import { renderDailyReport } from "@/server/skills/render-daily-report/runner";
import { validateReport } from "@/server/skills/validate-report/runner";

const DEFAULT_TIMEOUT_MS = 120_000;
const DEFAULT_MAX_REVISION_ROUNDS = 2;
const DEFAULT_MAX_EXECUTION_STEPS = 8;
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
};

type ExecutorDependencies = {
  render?: typeof renderDailyReport;
  validate?: typeof validateReport;
  now?: () => Date;
  checkpoint?: (execution: AgentRunExecutionResult) => Promise<void>;
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
    maxModelCalls: 0,
    maxRevisionRounds:
      input.maxRevisionRounds ?? DEFAULT_MAX_REVISION_ROUNDS,
    engineSnapshot: engineSnapshot(input.enginePayload),
    evidenceSnapshot: input.evidenceSnapshot ?? null,
    analysisSnapshot: input.analysisSnapshot ?? null,
  });
  if (state.human_review.decision !== null) {
    throw new Error("已提交人工决定的运行不可继续自动执行。");
  }
  const checkpoint = async (steps: number, terminalAction?: SupervisorAction) => {
    await dependencies.checkpoint?.({
      state,
      terminalAction: terminalAction ?? decideNextAction(state, CAPABILITIES, now().toISOString()),
      steps,
    });
  };
  await checkpoint(1);

  for (let steps = 1; steps <= DEFAULT_MAX_EXECUTION_STEPS; steps += 1) {
    const at = now().toISOString();
    const action = decideNextAction(state, CAPABILITIES, at);
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
        const details = errorDetails(error);
        state = recordCapabilityFailure(state, {
          agent: "report-delivery",
          capability: "render-daily-report",
          ...details,
          at: now().toISOString(),
        });
        state = recordTiming(state, at);
        const terminalAction = capabilityFailureAction(action, error);
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
        const { audit } = await validate({
          draft: state.report_draft,
          engineSnapshot: state.engine_snapshot,
          evidenceSnapshot: state.evidence_snapshot,
          analysisSnapshot: state.analysis_snapshot,
          templateVersion: input.templateVersion,
          version: state.report_draft.ref.version,
        });
        state = recordAuditResult(state, audit, now().toISOString());
        state = recordTiming(state, at);
      } catch (error) {
        const details = errorDetails(error);
        state = recordCapabilityFailure(state, {
          agent: "audit",
          capability: "validate-report",
          ...details,
          at: now().toISOString(),
        });
        state = recordTiming(state, at);
        const terminalAction = capabilityFailureAction(action, error);
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
