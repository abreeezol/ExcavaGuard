import "server-only";
import { z } from "zod";

const requiredValue = z.string().trim().min(1);
const httpUrl = z.url({ protocol: /^https?$/ });

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
