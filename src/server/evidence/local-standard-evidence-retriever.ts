import "server-only";
import { z } from "zod";
import {
  standardEvidenceCandidateSchema,
  standardEvidenceQuerySchema,
  type StandardEvidence,
  type StandardEvidenceQuery,
} from "@/contracts/standard-evidence";
import { EvidenceRetrievalError } from "@/server/evidence/errors";
import type { StandardEvidenceRetriever } from "@/server/evidence/retriever";

const localSearchResponseSchema = z.strictObject({
  evidence: z.array(standardEvidenceCandidateSchema).max(10),
});

type LocalRetrieverOptions = {
  baseUrl: string;
  timeoutMs: number;
  fetchImpl?: typeof fetch;
};

function parseLoopbackBaseUrl(value: string): URL {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new EvidenceRetrievalError(
      "RETRIEVER_NOT_CONFIGURED",
      "本地规范证据服务地址不合法。",
    );
  }

  const hostname = url.hostname.toLowerCase();
  const loopback =
    hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
  if (
    !loopback ||
    (url.protocol !== "http:" && url.protocol !== "https:") ||
    url.username !== "" ||
    url.password !== ""
  ) {
    throw new EvidenceRetrievalError(
      "RETRIEVER_NOT_CONFIGURED",
      "本地规范证据服务必须使用 loopback HTTP 地址。",
    );
  }
  return url;
}

export class LocalStandardEvidenceRetriever implements StandardEvidenceRetriever {
  readonly provider = "local" as const;
  private readonly endpoint: URL;
  private readonly fetchImpl: typeof fetch;

  constructor(private readonly options: LocalRetrieverOptions) {
    if (
      !Number.isInteger(options.timeoutMs) ||
      options.timeoutMs < 100 ||
      options.timeoutMs > 60_000
    ) {
      throw new EvidenceRetrievalError(
        "RETRIEVER_NOT_CONFIGURED",
        "本地规范证据服务超时配置不合法。",
      );
    }
    this.endpoint = new URL("/api/evidence/search", parseLoopbackBaseUrl(options.baseUrl));
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  async search(input: StandardEvidenceQuery): Promise<StandardEvidence[]> {
    const query = standardEvidenceQuerySchema.safeParse(input);
    if (!query.success) {
      throw new EvidenceRetrievalError("INVALID_QUERY", "规范证据检索参数不合法。");
    }

    let response: Response;
    try {
      response = await this.fetchImpl(this.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(query.data),
        redirect: "error",
        signal: AbortSignal.timeout(this.options.timeoutMs),
      });
    } catch (error) {
      throw new EvidenceRetrievalError(
        "RETRIEVER_UNAVAILABLE",
        "本地规范证据服务暂不可用。",
        { cause: error },
      );
    }

    if (!response.ok) {
      throw new EvidenceRetrievalError(
        "QUERY_FAILED",
        "本地规范证据服务拒绝了检索请求。",
      );
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch (error) {
      throw new EvidenceRetrievalError(
        "INVALID_RESPONSE",
        "本地规范证据服务返回了无效 JSON。",
        { cause: error },
      );
    }

    const parsed = localSearchResponseSchema.safeParse(payload);
    if (!parsed.success) {
      throw new EvidenceRetrievalError(
        "INVALID_RESPONSE",
        "本地规范证据服务返回了缺少来源字段的证据。",
      );
    }
    if (parsed.data.evidence.length > query.data.top_k) {
      throw new EvidenceRetrievalError(
        "INVALID_RESPONSE",
        "本地规范证据服务返回的证据数量超过请求上限。",
      );
    }

    return parsed.data.evidence.map((evidence) => ({
      ...evidence,
      provider: this.provider,
    }));
  }
}
