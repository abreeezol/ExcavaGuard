import "server-only";
import { createOpenAI } from "@ai-sdk/openai";
import type { LanguageModel } from "ai";
import { readIntegrationConfig } from "@/server/config";

// 仅返回模型适配器；本函数不发送请求，也不代表已验证供应商兼容性。
export function createLanguageModel(): LanguageModel {
  const config = readIntegrationConfig("llm");
  const provider = createOpenAI({
    apiKey: config.LLM_API_KEY,
    baseURL: config.LLM_BASE_URL,
  });
  return provider.chat(config.LLM_MODEL);
}
