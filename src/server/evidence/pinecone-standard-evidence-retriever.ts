import "server-only";
import { z } from "zod";
import {
  standardEvidenceCandidateSchema,
  standardEvidenceMetadataSchema,
  standardEvidenceQuerySchema,
  type ParsedStandardEvidenceQuery,
  type StandardEvidence,
  type StandardEvidenceQuery,
} from "@/contracts/standard-evidence";
import { EvidenceRetrievalError } from "@/server/evidence/errors";
import type {
  QueryEmbedder,
  StandardEvidenceRetriever,
} from "@/server/evidence/retriever";

const pineconeMetadataSchema = z.object({
  ...standardEvidenceMetadataSchema.shape,
  text: z.string().trim().min(1),
  matched_terms: z.array(z.string().trim().min(1)),
});

const pineconeQueryResponseSchema = z.object({
  matches: z
    .array(
      z.object({
        id: z.string(),
        score: z.float64().optional(),
        metadata: z.unknown().optional(),
      }),
    )
    .max(10),
});

type PineconeQueryOptions = {
  vector: number[];
  topK: number;
  includeMetadata: true;
  includeValues: false;
  filter: Record<string, unknown>;
};

type PineconeQueryMatch = {
  id: string;
  score?: number;
  metadata?: unknown;
};

export interface PineconeEvidenceIndex {
  query(options: PineconeQueryOptions): Promise<unknown>;
}

function buildPineconeFilter(
  filters: ParsedStandardEvidenceQuery["filters"],
): Record<string, unknown> {
  return {
    evidence_kind: { $eq: "standard" },
    effective_status: { $eq: filters.effective_status },
    ...(filters.standard_versions
      ? { standard_version: { $in: filters.standard_versions } }
      : {}),
    ...(filters.monitoring_item
      ? { monitoring_item: { $eq: filters.monitoring_item } }
      : {}),
    ...(filters.excavation_safety_level
      ? { excavation_safety_level: { $eq: filters.excavation_safety_level } }
      : {}),
    ...(filters.region ? { region: { $eq: filters.region } } : {}),
  };
}

export class PineconeStandardEvidenceRetriever implements StandardEvidenceRetriever {
  readonly provider = "pinecone" as const;

  constructor(
    private readonly index: PineconeEvidenceIndex,
    private readonly embedQuery: QueryEmbedder,
  ) {}

  async search(input: StandardEvidenceQuery): Promise<StandardEvidence[]> {
    const query = standardEvidenceQuerySchema.safeParse(input);
    if (!query.success) {
      throw new EvidenceRetrievalError("INVALID_QUERY", "规范证据检索参数不合法。");
    }

    let vector: readonly number[];
    try {
      vector = await this.embedQuery(query.data.query);
    } catch (error) {
      throw new EvidenceRetrievalError(
        "QUERY_FAILED",
        "规范证据查询向量生成失败。",
        { cause: error },
      );
    }

    if (
      !Array.isArray(vector) ||
      vector.length === 0 ||
      vector.some((value) => typeof value !== "number" || !Number.isFinite(value))
    ) {
      throw new EvidenceRetrievalError(
        "INVALID_RESPONSE",
        "规范证据查询向量不完整。",
      );
    }

    let rawResponse: unknown;
    try {
      rawResponse = await this.index.query({
        vector: [...vector],
        topK: query.data.top_k,
        includeMetadata: true,
        includeValues: false,
        filter: buildPineconeFilter(query.data.filters),
      });
    } catch (error) {
      throw new EvidenceRetrievalError(
        "RETRIEVER_UNAVAILABLE",
        "Pinecone 规范证据检索暂不可用。",
        { cause: error },
      );
    }

    const response = pineconeQueryResponseSchema.safeParse(rawResponse);
    if (!response.success) {
      throw new EvidenceRetrievalError(
        "INVALID_RESPONSE",
        "Pinecone 返回了无效的规范证据响应。",
      );
    }
    if (response.data.matches.length > query.data.top_k) {
      throw new EvidenceRetrievalError(
        "INVALID_RESPONSE",
        "Pinecone 返回的规范证据数量超过请求上限。",
      );
    }

    return response.data.matches.map((match: PineconeQueryMatch) => {
      const metadata = pineconeMetadataSchema.safeParse(match.metadata);
      let candidate = null;
      if (metadata.success) {
        const { text, matched_terms, ...evidenceMetadata } = metadata.data;
        candidate = standardEvidenceCandidateSchema.safeParse({
          id: match.id,
          text,
          metadata: evidenceMetadata,
          score: match.score,
          matched_terms,
        });
      }

      if (!candidate?.success) {
        throw new EvidenceRetrievalError(
          "INVALID_RESPONSE",
          "Pinecone 返回了缺少来源字段的规范证据。",
        );
      }

      return { ...candidate.data, provider: this.provider };
    });
  }
}
