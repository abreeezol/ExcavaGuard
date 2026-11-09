import { callSkillScript } from "@/server/skills/python-bridge";
import { standardEvidenceSchema } from "@/contracts/standard-evidence";
import "server-only";
import { z } from "zod";
import { Pinecone } from "@pinecone-database/pinecone";
import { readStandardCatalog } from "@/server/evidence/standard-catalog";
import { loadEngineeringAdapter } from "@/server/engineering-adapters/registry";
import { LocalStandardEvidenceRetriever } from "@/server/evidence/local-standard-evidence-retriever";
import {
  PineconeStandardEvidenceRetriever,
  type PineconeEvidenceIndex,
} from "@/server/evidence/pinecone-standard-evidence-retriever";
import type { StandardEvidenceRetriever } from "@/server/evidence/retriever";
import { readIntegrationConfig } from "@/server/config";
import { createPineconeIndex } from "@/server/integrations/pinecone";

type RetrieverFactoryDependencies = {
  sceneParameters?:Record<string,unknown>;
  adapterId?: string;
  fetchImpl?: typeof fetch;
  pineconeIndex?: PineconeEvidenceIndex;
  pineconeTextField?: string;
  signal?: AbortSignal;
};

export function createStandardEvidenceRetriever(
  dependencies: RetrieverFactoryDependencies = {},
): StandardEvidenceRetriever {
  const { adapter } = loadEngineeringAdapter(dependencies.adapterId);
  if (adapter.retrieval.local_index) {
    const allowed=adapter.standard_scope?readStandardCatalog(adapter.id,dependencies.sceneParameters??{}).filter(s=>s.effective_status==='active'&&s.applicable!==false).map(s=>s.standard_version):null;
    return { provider: "local", search: async query => {
    const requested=query.filters?.standard_versions;
    const versions=allowed?(requested?allowed.filter(v=>requested.includes(v)):allowed):requested;
    if(versions&&!versions.length)return [];
    const scopedQuery={...query,filters:{...query.filters,...(versions?{standard_versions:versions}:{})}};
    const result=await callSkillScript("adapter-knowledge","query.py",{adapter_id:adapter.id,query:scopedQuery,scene_parameters:dependencies.sceneParameters},{adapterId:adapter.id});
    return z.array(standardEvidenceSchema).parse(result.result);
  }}; }
  if (adapter.retrieval.connection !== "legacy-pit") {
    const schema = z.discriminatedUnion("provider", [
      z.object({ provider: z.literal("local"), base_url: z.string().url(), timeout_ms: z.number().int().min(100).max(60000).default(30000) }),
      z.object({ provider: z.literal("pinecone"), index: z.string().min(1), namespace: z.string().optional(),
        api_key_env: z.string().regex(/^[A-Z][A-Z0-9_]+$/), text_field: z.string().default("text") }),
    ]);
    const connections = JSON.parse(process.env.EXCAVAGUARD_RAG_CONNECTIONS ?? "{}");
    const parsed = schema.safeParse(connections[adapter.retrieval.connection]);
    if (!parsed.success) throw new Error("ADAPTER_RAG_NOT_CONFIGURED：未配置当前场景独立检索连接。");
    const config = parsed.data;
    if (config.provider === "local") return new LocalStandardEvidenceRetriever({ baseUrl: config.base_url,
      timeoutMs: config.timeout_ms, fetchImpl: dependencies.fetchImpl, signal: dependencies.signal });
    const apiKey = process.env[config.api_key_env];
    if (!apiKey && !dependencies.pineconeIndex) throw new Error("ADAPTER_RAG_NOT_CONFIGURED");
    const index = dependencies.pineconeIndex ?? new Pinecone({ apiKey: apiKey!, maxRetries: 2 }).index({
      name: config.index, ...(config.namespace ? { namespace: config.namespace } : {}),
    });
    return new PineconeStandardEvidenceRetriever(index, config.text_field);
  }
  if (adapter.id !== "foundation-pit") throw new Error("ADAPTER_RAG_SCOPE_CONFLICT");
  const { RAG_PROVIDER } = readIntegrationConfig("rag");

  if (RAG_PROVIDER === "local") {
    const config = readIntegrationConfig("localRag");
    return new LocalStandardEvidenceRetriever({
      baseUrl: config.LOCAL_RAG_BASE_URL,
      timeoutMs: config.LOCAL_RAG_TIMEOUT_MS,
      fetchImpl: dependencies.fetchImpl,
      signal: dependencies.signal,
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
    createPineconeIndex(dependencies.signal),
    config.PINECONE_TEXT_FIELD,
  );
}
