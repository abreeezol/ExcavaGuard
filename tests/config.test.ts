import { afterEach, describe, expect, it, vi } from "vitest";
import { IntegrationConfigError, readIntegrationConfig } from "@/server/config";
import { createLanguageModel } from "@/server/integrations/llm";
import { createSupabaseAdmin } from "@/server/integrations/supabase";
import { createPineconeIndex } from "@/server/integrations/pinecone";

afterEach(() => vi.unstubAllEnvs());

describe("服务端配置", () => {
  it("合法配置只返回当前服务需要的字段", () => {
    vi.stubEnv("LLM_API_KEY", "test-only-key");
    vi.stubEnv("LLM_BASE_URL", "https://example.invalid/v1");
    vi.stubEnv("LLM_MODEL", "test-only-model");
    vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "unrelated-test-key");
    expect(readIntegrationConfig("llm")).toEqual({
      LLM_API_KEY: "test-only-key",
      LLM_BASE_URL: "https://example.invalid/v1",
      LLM_MODEL: "test-only-model",
    });
  });

  it("不默认为用户选择模型", () => {
    vi.stubEnv("LLM_API_KEY", "test-only-key");
    vi.stubEnv("LLM_BASE_URL", "https://example.invalid/v1");
    vi.stubEnv("LLM_MODEL", " ");
    expect(createLanguageModel).toThrow(IntegrationConfigError);
  });

  it("非法 URL 的错误不携带输入或密钥", () => {
    vi.stubEnv("LLM_API_KEY", "test-only-secret-canary");
    vi.stubEnv("LLM_BASE_URL", "file:///test-only-secret-canary");
    vi.stubEnv("LLM_MODEL", "test-only-model");
    expect(() => readIntegrationConfig("llm")).toThrow("llm 配置缺失或不合法。");
  });

  it.each([
    ["SUPABASE_SERVICE_ROLE_KEY", createSupabaseAdmin],
    ["PINECONE_API_KEY", createPineconeIndex],
  ] as const)("缺少 %s 时在创建客户端前失败", (key, factory) => {
    vi.stubEnv(key, "");
    expect(factory).toThrow(IntegrationConfigError);
  });
});
