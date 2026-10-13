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
import type { StandardEvidenceRetriever } from "@/server/evidence/retriever";

const pineconeMetadataSchema = z.object(standardEvidenceMetadataSchema.shape);
const pineconeRecordFieldsSchema = z.record(z.string(), z.unknown());
const pineconeTextSchema = z.string().trim().min(1);
const PINECONE_METADATA_FIELDS = [
  "standard_name",
  "standard_version",
  "clause",
  "source_location",
  "applicability",
  "effective_status",
  "monitoring_item",
  "excavation_safety_level",
  "region",
] as const;
const reservedFieldNames = new Set<string>([
  "_id",
  "_score",
  "evidence_kind",
  "standard_code",
  "source_category",
  "source_name",
  "registry_relevance",
  ...PINECONE_METADATA_FIELDS,
]);
const pineconeTextFieldSchema = z
  .string()
  .trim()
  .min(1)
  .max(128)
  .refine((value) => !reservedFieldNames.has(value));

const pineconeSearchResponseSchema = z.object({
  result: z.object({
    hits: z
      .array(
        z.object({
          _id: z.string().trim().min(1),
          _score: z.float64(),
          fields: z.unknown(),
        }),
      )
      .max(10),
  }),
});

type PineconeSearchOptions = {
  query: {
    inputs: { text: string };
    topK: number;
    filter: Record<string, unknown>;
  };
  fields: string[];
};

export interface PineconeEvidenceIndex {
  searchRecords(options: PineconeSearchOptions): Promise<unknown>;
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
  private readonly textField: string;

  constructor(
    private readonly index: PineconeEvidenceIndex,
    textField = "chunk_text",
  ) {
    const parsedTextField = pineconeTextFieldSchema.safeParse(textField);
    if (!parsedTextField.success) {
      throw new EvidenceRetrievalError(
        "RETRIEVER_NOT_CONFIGURED",
        "Pinecone integrated embedding 文本字段配置不合法。",
      );
    }
    this.textField = parsedTextField.data;
  }

  async search(input: StandardEvidenceQuery): Promise<StandardEvidence[]> {
    const query = standardEvidenceQuerySchema.safeParse(input);
    if (!query.success) {
      throw new EvidenceRetrievalError("INVALID_QUERY", "规范证据检索参数不合法。");
    }

    let rawResponse: unknown;
    try {
      rawResponse = await this.index.searchRecords({
        query: {
          inputs: { text: query.data.query },
          topK: query.data.top_k,
          filter: buildPineconeFilter(query.data.filters),
        },
        fields: [this.textField, ...PINECONE_METADATA_FIELDS],
      });
    } catch (error) {
      throw new EvidenceRetrievalError(
        "RETRIEVER_UNAVAILABLE",
        "Pinecone 规范证据检索暂不可用。",
        { cause: error },
      );
    }

    const response = pineconeSearchResponseSchema.safeParse(rawResponse);
    if (!response.success) {
      throw new EvidenceRetrievalError(
        "INVALID_RESPONSE",
        "Pinecone 返回了无效的规范证据响应。",
      );
    }
    if (response.data.result.hits.length > query.data.top_k) {
      throw new EvidenceRetrievalError(
        "INVALID_RESPONSE",
        "Pinecone 返回的规范证据数量超过请求上限。",
      );
    }

    return response.data.result.hits.map((hit) => {
      const fields = pineconeRecordFieldsSchema.safeParse(hit.fields);
      let candidate = null;
      if (fields.success) {
        const text = pineconeTextSchema.safeParse(
          fields.data[this.textField],
        );
        const metadata = pineconeMetadataSchema.safeParse(fields.data);
        if (!text.success || !metadata.success) {
          throw new EvidenceRetrievalError(
            "INVALID_RESPONSE",
            "Pinecone 返回了缺少来源字段的规范证据。",
          );
        }
        candidate = standardEvidenceCandidateSchema.safeParse({
          id: hit._id,
          text: text.data,
          metadata: metadata.data,
          score: hit._score,
          matched_terms: [],
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
