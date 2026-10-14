import { createServer } from "node:http";
import { afterEach, describe, expect, it, vi } from "vitest";
import { invokeReportModel } from "@/server/agents/report-model";

describe("OpenAI-compatible 模型客户端（本机 HTTP 模拟服务）", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("三个角色通过真实 HTTP 客户端接收结构化输出，不隐式重试", async () => {
    const requests: Record<string, unknown>[] = [];
    const paragraph = { text: "资料不足，请工程师复核。", evidence_ids: [] };
    const responses = [
      { focus_indices: [0], evidence_topics: ["测试"] },
      { work_condition: paragraph, analysis: [paragraph], recommendations: [paragraph],
        limitations: [paragraph], appendix_analysis: [] },
      { issues: [] },
    ];
    const server = createServer(async (request, response) => {
      let body = "";
      for await (const chunk of request) body += String(chunk);
      requests.push(JSON.parse(body));
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({
        id: "test-completion", object: "chat.completion", created: 1, model: "test-model",
        choices: [{ index: 0, message: { role: "assistant", content: JSON.stringify(responses[requests.length - 1]) }, finish_reason: "stop" }],
        usage: { prompt_tokens: 10, completion_tokens: 20, total_tokens: 30 },
      }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("本机测试服务启动失败。");
    vi.stubEnv("LLM_BASE_URL", `http://127.0.0.1:${address.port}/v1`);
    vi.stubEnv("LLM_API_KEY", "local-test-only-key");
    vi.stubEnv("LLM_MODEL", "test-model");
    try {
      for (const [index, role] of (["supervisor", "report-delivery", "audit"] as const).entries()) {
        const result = await invokeReportModel({ role, context: { test: "固定输入" }, timeoutMs: 5000 });
        expect(result.object).toEqual(responses[index]);
        expect(result.usage).toEqual({ input_tokens: 10, output_tokens: 20 });
      }
      expect(requests).toHaveLength(3);
      expect(requests.every((request) => request.model === "test-model")).toBe(true);
      expect(new Set(requests.map((request) => JSON.stringify(request.messages))).size).toBe(3);
    } finally {
      server.closeAllConnections();
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    }
  });
});
