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
    vi.stubEnv("SUPABASE_SECRET_KEY", "sb_secret_unrelated-test-key");
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

  it("本地 RAG 只接受 loopback 地址并解析超时", () => {
    vi.stubEnv("LOCAL_RAG_BASE_URL", "http://127.0.0.1:8600");
    vi.stubEnv("LOCAL_RAG_TIMEOUT_MS", "2500");
    expect(readIntegrationConfig("localRag")).toEqual({
      LOCAL_RAG_BASE_URL: "http://127.0.0.1:8600",
      LOCAL_RAG_TIMEOUT_MS: 2500,
    });

    vi.stubEnv("LOCAL_RAG_BASE_URL", "https://rag.example.com");
    expect(() => readIntegrationConfig("localRag")).toThrow(IntegrationConfigError);
  });

  it("RAG Provider 必须显式选择", () => {
    vi.stubEnv("RAG_PROVIDER", "");
    expect(() => readIntegrationConfig("rag")).toThrow(IntegrationConfigError);
    vi.stubEnv("RAG_PROVIDER", "local");
    expect(readIntegrationConfig("rag")).toEqual({ RAG_PROVIDER: "local" });
  });

  it("Pinecone 文本字段可配置并保持兼容默认值", () => {
    vi.stubEnv("PINECONE_API_KEY", "test-only-key");
    vi.stubEnv("PINECONE_INDEX", "test-index");
    vi.stubEnv("PINECONE_TEXT_FIELD", "");
    expect(readIntegrationConfig("pinecone")).toEqual({
      PINECONE_API_KEY: "test-only-key",
      PINECONE_INDEX: "test-index",
      PINECONE_NAMESPACE: undefined,
      PINECONE_TEXT_FIELD: "chunk_text",
    });

    vi.stubEnv("PINECONE_TEXT_FIELD", "text");
    expect(readIntegrationConfig("pinecone").PINECONE_TEXT_FIELD).toBe("text");
  });

  it.each([
    ["SUPABASE_SECRET_KEY", createSupabaseAdmin],
    ["PINECONE_API_KEY", createPineconeIndex],
  ] as const)("缺少 %s 时在创建客户端前失败", (key, factory) => {
    vi.stubEnv(key, "");
    expect(factory).toThrow(IntegrationConfigError);
  });

  it("Supabase 公共配置只接受 publishable key", () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test-only");
    expect(readIntegrationConfig("supabasePublic")).toEqual({
      NEXT_PUBLIC_SUPABASE_URL: "https://example.supabase.co",
      NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "sb_publishable_test-only",
    });

    vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "sb_secret_must-not-be-public");
    expect(() => readIntegrationConfig("supabasePublic")).toThrow(IntegrationConfigError);
  });

  it("Supabase 服务端配置复用公共 URL，但只接受新式 secret key", () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co");
    vi.stubEnv("SUPABASE_SECRET_KEY", "sb_secret_test-only");
    vi.stubEnv("SUPABASE_STORAGE_BUCKET", "excavaguard-private");
    expect(readIntegrationConfig("supabase")).toEqual({
      SUPABASE_URL: "https://example.supabase.co",
      SUPABASE_SECRET_KEY: "sb_secret_test-only",
      SUPABASE_STORAGE_BUCKET: "excavaguard-private",
    });

    vi.stubEnv("SUPABASE_SECRET_KEY", "sb_publishable_wrong-role");
    expect(() => readIntegrationConfig("supabase")).toThrow(IntegrationConfigError);

    vi.stubEnv("SUPABASE_SECRET_KEY", "sb_secret_test-only");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://attacker.example.com");
    expect(() => readIntegrationConfig("supabase")).toThrow(IntegrationConfigError);
  });
});
