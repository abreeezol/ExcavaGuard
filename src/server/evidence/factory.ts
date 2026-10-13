import "server-only";
import { LocalStandardEvidenceRetriever } from "@/server/evidence/local-standard-evidence-retriever";
import {
  PineconeStandardEvidenceRetriever,
  type PineconeEvidenceIndex,
} from "@/server/evidence/pinecone-standard-evidence-retriever";
import type { StandardEvidenceRetriever } from "@/server/evidence/retriever";
import { readIntegrationConfig } from "@/server/config";
import { createPineconeIndex } from "@/server/integrations/pinecone";

type RetrieverFactoryDependencies = {
  fetchImpl?: typeof fetch;
  pineconeIndex?: PineconeEvidenceIndex;
  pineconeTextField?: string;
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

  if (dependencies.pineconeIndex) {
    return new PineconeStandardEvidenceRetriever(
      dependencies.pineconeIndex,
      dependencies.pineconeTextField,
    );
  }

  const config = readIntegrationConfig("pinecone");
  return new PineconeStandardEvidenceRetriever(
    createPineconeIndex(),
    config.PINECONE_TEXT_FIELD,
  );
}
