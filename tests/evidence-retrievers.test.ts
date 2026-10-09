import { afterEach, describe, expect, it, vi } from "vitest";
import type { StandardEvidenceCandidate } from "@/contracts/standard-evidence";
import { EvidenceRetrievalError } from "@/server/evidence/errors";
import { createStandardEvidenceRetriever } from "@/server/evidence/factory";
import { LocalStandardEvidenceRetriever } from "@/server/evidence/local-standard-evidence-retriever";
import {
  PineconeStandardEvidenceRetriever,
  type PineconeEvidenceIndex,
} from "@/server/evidence/pinecone-standard-evidence-retriever";

const candidate: StandardEvidenceCandidate = {
  id: "std-gb50497-2019-8.0.1",
  text: "仅用于测试的规范条文占位文本，不代表真实工程要求。",
  metadata: {
    standard_name: "测试规范",
    standard_version: "demo-2026",
    clause: "8.0.1",
    source_location: "测试页 1",
    applicability: ["仅用于自动化测试"],
    effective_status: "active",
    monitoring_item: "测试监测项",
    excavation_safety_level: "demo",
    region: "测试区域",
  },
  score: 0.91,
  matched_terms: ["测试监测项"],
};

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("Pinecone 规范证据适配器", () => {
  it("应用元数据过滤并返回统一证据结构", async () => {
    const query = vi.fn<PineconeEvidenceIndex["query"]>().mockResolvedValue({
      matches: [
        {
          id: candidate.id,
          score: candidate.score,
          metadata: {
            ...candidate.metadata,
            text: candidate.text,
            matched_terms: candidate.matched_terms,
            ignored_index_field: "允许索引包含额外元数据",
          },
        },
      ],
    });
    const retriever = new PineconeStandardEvidenceRetriever(
      { query },
      async () => [0.1, 0.2, 0.3],
    );

    await expect(
      retriever.search({
        query: "测试监测项适用什么规范",
        filters: {
          standard_versions: ["demo-2026"],
          monitoring_item: "测试监测项",
          excavation_safety_level: "demo",
          region: "测试区域",
        },
      }),
    ).resolves.toEqual([{ ...candidate, provider: "pinecone" }]);

    expect(query).toHaveBeenCalledWith({
      vector: [0.1, 0.2, 0.3],
      topK: 3,
      includeMetadata: true,
      includeValues: false,
      filter: {
        evidence_kind: { $eq: "standard" },
        effective_status: { $eq: "active" },
        standard_version: { $in: ["demo-2026"] },
        monitoring_item: { $eq: "测试监测项" },
        excavation_safety_level: { $eq: "demo" },
        region: { $eq: "测试区域" },
      },
    });
  });

  it("拒绝空向量和缺少规范版本的索引记录", async () => {
    const index: PineconeEvidenceIndex = {
      query: vi.fn().mockResolvedValue({
        matches: [
          {
            id: candidate.id,
            score: candidate.score,
            metadata: {
              ...candidate.metadata,
              standard_version: undefined,
              text: candidate.text,
              matched_terms: candidate.matched_terms,
            },
          },
        ],
      }),
    };

    const emptyEmbedding = new PineconeStandardEvidenceRetriever(index, async () => []);
    await expect(emptyEmbedding.search({ query: "测试" })).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });

    const retriever = new PineconeStandardEvidenceRetriever(index, async () => [0.1]);
    await expect(retriever.search({ query: "测试" })).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });

  it("拒绝 Pinecone 非预期响应结构", async () => {
    const retriever = new PineconeStandardEvidenceRetriever(
      { query: vi.fn().mockResolvedValue({ matches: null }) },
      async () => [0.1],
    );
    await expect(retriever.search({ query: "测试" })).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });
});

describe("本地规范证据适配器", () => {
  it("使用 POST 调用 loopback 服务并标记本地 Provider", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json({ evidence: [candidate] }));
    const retriever = new LocalStandardEvidenceRetriever({
      baseUrl: "http://127.0.0.1:8600",
      timeoutMs: 1_000,
      fetchImpl: fetchMock as unknown as typeof fetch,
    });

    await expect(retriever.search({ query: "测试规范" })).resolves.toEqual([
      { ...candidate, provider: "local" },
    ]);

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://127.0.0.1:8600/api/evidence/search");
    expect(init).toMatchObject({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      redirect: "error",
    });
    expect(JSON.parse(String(init?.body))).toEqual({
      query: "测试规范",
      filters: { effective_status: "active" },
      top_k: 3,
    });
  });

  it("拒绝远端地址、旧版响应和超量结果", async () => {
    expect(
      () =>
        new LocalStandardEvidenceRetriever({
          baseUrl: "https://rag.example.com",
          timeoutMs: 1_000,
        }),
    ).toThrow(EvidenceRetrievalError);
    expect(
      () =>
        new LocalStandardEvidenceRetriever({
          baseUrl: "http://127.0.0.1:8600",
          timeoutMs: 0,
        }),
    ).toThrow("本地规范证据服务超时配置不合法。");

    const retriever = new LocalStandardEvidenceRetriever({
      baseUrl: "http://localhost:8600",
      timeoutMs: 1_000,
      fetchImpl: vi.fn(async () =>
        Response.json({
          hits: [{ source: "测试规范", clause: "8.0.1", content: "不完整条文" }],
        }),
      ) as unknown as typeof fetch,
    });
    await expect(retriever.search({ query: "测试规范" })).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });

    const excessiveRetriever = new LocalStandardEvidenceRetriever({
      baseUrl: "http://localhost:8600",
      timeoutMs: 1_000,
      fetchImpl: vi
        .fn<typeof fetch>()
        .mockResolvedValue(Response.json({ evidence: [candidate, candidate] })),
    });
    await expect(
      excessiveRetriever.search({ query: "测试规范", top_k: 1 }),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("不把本地服务错误正文带入异常", async () => {
    const retriever = new LocalStandardEvidenceRetriever({
      baseUrl: "http://[::1]:8600",
      timeoutMs: 1_000,
      fetchImpl: vi.fn(async () =>
        Response.json(
          { error: "test-only-secret-canary" },
          { status: 500 },
        ),
      ) as unknown as typeof fetch,
    });

    await expect(retriever.search({ query: "测试规范" })).rejects.toEqual(
      expect.objectContaining({
        code: "QUERY_FAILED",
        message: "本地规范证据服务拒绝了检索请求。",
      }),
    );
  });
});

describe("规范证据适配器工厂", () => {
  it("本地模式不需要 Pinecone 或 Embedding 配置", () => {
    vi.stubEnv("RAG_PROVIDER", "local");
    vi.stubEnv("LOCAL_RAG_BASE_URL", "http://127.0.0.1:8600");
    vi.stubEnv("LOCAL_RAG_TIMEOUT_MS", "2000");
    expect(createStandardEvidenceRetriever().provider).toBe("local");
  });

  it("Pinecone 模式未注入 Embedding 时明确失败", () => {
    vi.stubEnv("RAG_PROVIDER", "pinecone");
    expect(() => createStandardEvidenceRetriever()).toThrow(
      "Pinecone 规范证据检索尚未配置查询 Embedding。",
    );
  });
});
