import "server-only";
import { z } from "zod";
import {
  standardEvidenceFiltersSchema,
  type StandardEvidence,
} from "@/contracts/standard-evidence";
import { createStandardEvidenceRetriever } from "@/server/evidence/factory";
import type {
  StandardEvidenceProvider,
  StandardEvidenceRetriever,
} from "@/server/evidence/retriever";

const inputSchema = z.strictObject({
  query: z.string().trim().min(1).max(1_000),
  filters: standardEvidenceFiltersSchema.optional(),
  limit: z.number().int().min(1).max(10).default(3),
});

const NOTICE =
  "检索结果仅作为规范证据候选，适用性、版本有效性和工程使用须由专业工程师复核。";

type EvidenceTrace = {
  provider: StandardEvidenceProvider | "unavailable";
  query: string;
  filters: z.output<typeof standardEvidenceFiltersSchema>;
  limit: number;
  hit_count: number;
  evidence_ids: string[];
};

type EvidenceSuccess = {
  status: "success";
  evidence: StandardEvidence[];
  notice: string;
  trace: EvidenceTrace;
};

type EvidenceAbstention = {
  status: "abstained";
  code: "INVALID_INPUT" | "EVIDENCE_NOT_FOUND" | "EVIDENCE_CONFLICT" | "EVIDENCE_UNAVAILABLE";
  message: string;
  evidence: StandardEvidence[];
  notice: string;
  trace: EvidenceTrace;
};

export type StandardEvidenceSkillResult =
  | EvidenceSuccess
  | EvidenceAbstention;

type RunnerDependencies = {
  retriever?: StandardEvidenceRetriever;
  signal?: AbortSignal;
};

function emptyTrace(): EvidenceTrace {
  return {
    provider: "unavailable",
    query: "",
    filters: { effective_status: "active" },
    limit: 3,
    hit_count: 0,
    evidence_ids: [],
  };
}

export async function retrieveStandardEvidence(
  input: unknown,
  dependencies: RunnerDependencies = {},
): Promise<StandardEvidenceSkillResult> {
  const parsed = inputSchema.safeParse(input);
  if (!parsed.success) {
    return {
      status: "abstained",
      code: "INVALID_INPUT",
      message: "规范证据检索参数不合法。",
      evidence: [],
      notice: NOTICE,
      trace: emptyTrace(),
    };
  }

  const filters = standardEvidenceFiltersSchema.parse(parsed.data.filters ?? {});
  let retriever: StandardEvidenceRetriever;
  try {
    retriever =
      dependencies.retriever ?? createStandardEvidenceRetriever({ signal: dependencies.signal });
  } catch {
    return {
      status: "abstained",
      code: "EVIDENCE_UNAVAILABLE",
      message: "规范证据检索器未配置或暂不可用。",
      evidence: [],
      notice: NOTICE,
      trace: {
        ...emptyTrace(),
        query: parsed.data.query,
        filters,
        limit: parsed.data.limit,
      },
    };
  }

  let evidence: StandardEvidence[];
  try {
    evidence = await retriever.search({
      query: parsed.data.query,
      filters,
      top_k: parsed.data.limit,
    });
  } catch {
    return {
      status: "abstained",
      code: "EVIDENCE_UNAVAILABLE",
      message: "规范证据检索失败，不能形成规范性结论。",
      evidence: [],
      notice: NOTICE,
      trace: {
        provider: retriever.provider,
        query: parsed.data.query,
        filters,
        limit: parsed.data.limit,
        hit_count: 0,
        evidence_ids: [],
      },
    };
  }

  const trace: EvidenceTrace = {
    provider: retriever.provider,
    query: parsed.data.query,
    filters,
    limit: parsed.data.limit,
    hit_count: evidence.length,
    evidence_ids: evidence.map((item) => item.id),
  };
  if (evidence.length === 0) {
    return {
      status: "abstained",
      code: "EVIDENCE_NOT_FOUND",
      message: "未检索到满足条件的规范条文，不能形成规范性结论。",
      evidence: [],
      notice: NOTICE,
      trace,
    };
  }

  if (
    evidence.some(
      (item) => item.metadata.effective_status !== "active",
    )
  ) {
    return {
      status: "abstained",
      code: "EVIDENCE_CONFLICT",
      message: "检索结果包含非现行或状态未确认的规范证据，需人工复核。",
      evidence,
      notice: NOTICE,
      trace,
    };
  }

  return {
    status: "success",
    evidence,
    notice: NOTICE,
    trace,
  };
}
