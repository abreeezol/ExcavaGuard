import "server-only";
import { z } from "zod";

const requiredValue = z.string().trim().min(1);
const httpUrl = z.url({ protocol: /^https?$/ });
const optionalValue = z.preprocess(
  (value) => (value === "" ? undefined : value),
  requiredValue.optional(),
);
const loopbackUrl = httpUrl.refine((value) => {
  const hostname = new URL(value).hostname.toLowerCase();
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
});

const integrationSchemas = {
  llm: z.object({
    LLM_API_KEY: requiredValue,
    LLM_BASE_URL: httpUrl,
    LLM_MODEL: requiredValue,
  }),
  supabase: z.object({
    SUPABASE_URL: httpUrl,
    SUPABASE_SERVICE_ROLE_KEY: requiredValue,
    SUPABASE_STORAGE_BUCKET: requiredValue,
  }),
  pinecone: z.object({
    PINECONE_API_KEY: requiredValue,
    PINECONE_INDEX: requiredValue,
    PINECONE_NAMESPACE: optionalValue,
  }),
  rag: z.object({
    RAG_PROVIDER: z.enum(["pinecone", "local"]),
  }),
  localRag: z.object({
    LOCAL_RAG_BASE_URL: loopbackUrl,
    LOCAL_RAG_TIMEOUT_MS: z.coerce.number().int().min(100).max(60_000).default(10_000),
  }),
};

type Integration = keyof typeof integrationSchemas;
type IntegrationConfig<K extends Integration> = z.output<(typeof integrationSchemas)[K]>;

export class IntegrationConfigError extends Error {
  readonly code = "INTEGRATION_NOT_CONFIGURED";

  constructor(readonly integration: Integration) {
    // 不附带原始环境变量或 Zod 输入，防止密钥进入错误信息。
    super(`${integration} 配置缺失或不合法。`);
    this.name = "IntegrationConfigError";
  }
}

export function readIntegrationConfig<K extends Integration>(
  integration: K,
): IntegrationConfig<K> {
  const result = integrationSchemas[integration].safeParse(process.env);
  if (!result.success) {
    throw new IntegrationConfigError(integration);
  }
  return result.data as IntegrationConfig<K>;
}
