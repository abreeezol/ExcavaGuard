import "server-only";
import { EvidenceRetrievalError } from "@/server/evidence/errors";
import { LocalStandardEvidenceRetriever } from "@/server/evidence/local-standard-evidence-retriever";
import {
  PineconeStandardEvidenceRetriever,
  type PineconeEvidenceIndex,
} from "@/server/evidence/pinecone-standard-evidence-retriever";
import type {
  QueryEmbedder,
  StandardEvidenceRetriever,
} from "@/server/evidence/retriever";
import { readIntegrationConfig } from "@/server/config";
import { createPineconeIndex } from "@/server/integrations/pinecone";

type RetrieverFactoryDependencies = {
  embedQuery?: QueryEmbedder;
  fetchImpl?: typeof fetch;
  pineconeIndex?: PineconeEvidenceIndex;
};

export function createStandardEvidenceRetriever(
  dependencies: RetrieverFactoryDependencies = {},
): StandardEvidenceRetriever {
  const { RAG_PROVIDER } = readIntegrationConfig("rag");

  if (RAG_PROVIDER === "local") {
    const config = readIntegrationConfig("localRag");
    return new LocalStandardEvidenceRetriever({
      baseUrl: config.LOCAL_RAG_BASE_URL,
      timeoutMs: config.LOCAL_RAG_TIMEOUT_MS,
      fetchImpl: dependencies.fetchImpl,
    });
  }

  if (!dependencies.embedQuery) {
    throw new EvidenceRetrievalError(
      "RETRIEVER_NOT_CONFIGURED",
      "Pinecone 规范证据检索尚未配置查询 Embedding。",
    );
  }

  const index = dependencies.pineconeIndex ?? createPineconeIndex();
  return new PineconeStandardEvidenceRetriever(index, dependencies.embedQuery);
}
