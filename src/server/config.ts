import "server-only";
import { z } from "zod";

const requiredValue = z.string().trim().min(1);
const httpUrl = z.url({ protocol: /^https?$/ });
const optionalValue = z.preprocess(
  (value) => (value === "" ? undefined : value),
  requiredValue.optional(),
);
const supabaseUrl = httpUrl.refine((value) => {
  const url = new URL(value);
  const hostname = url.hostname.toLowerCase();
  return (
    (url.protocol === "https:" && hostname.endsWith(".supabase.co")) ||
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "[::1]"
  );
});
const optionalSupabaseUrl = z.preprocess(
  (value) => (value === "" ? undefined : value),
  supabaseUrl.optional(),
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
  supabasePublic: z
    .object({
      NEXT_PUBLIC_SUPABASE_URL: supabaseUrl,
      NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: requiredValue.regex(/^sb_publishable_/),
    }),
  supabase: z
    .object({
      SUPABASE_URL: optionalSupabaseUrl,
      NEXT_PUBLIC_SUPABASE_URL: optionalSupabaseUrl,
      SUPABASE_SECRET_KEY: requiredValue.regex(/^sb_secret_/),
      SUPABASE_STORAGE_BUCKET: requiredValue,
    })
    .superRefine((value, context) => {
      if (!value.SUPABASE_URL && !value.NEXT_PUBLIC_SUPABASE_URL) {
        context.addIssue({
          code: "custom",
          path: ["SUPABASE_URL"],
          message: "缺少 Supabase URL。",
        });
      }
    })
    .transform((value) => ({
      SUPABASE_URL: value.SUPABASE_URL ?? value.NEXT_PUBLIC_SUPABASE_URL!,
      SUPABASE_SECRET_KEY: value.SUPABASE_SECRET_KEY,
      SUPABASE_STORAGE_BUCKET: value.SUPABASE_STORAGE_BUCKET,
    })),
  pinecone: z.object({
    PINECONE_API_KEY: requiredValue,
    PINECONE_INDEX: requiredValue,
    PINECONE_NAMESPACE: optionalValue,
    PINECONE_TEXT_FIELD: z.preprocess(
      (value) => (value === "" ? undefined : value),
      requiredValue.default("chunk_text"),
    ),
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
