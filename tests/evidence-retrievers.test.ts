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
  it("使用 integrated embedding 文本查询并返回统一证据结构", async () => {
    const searchRecords = vi
      .fn<PineconeEvidenceIndex["searchRecords"]>()
      .mockResolvedValue({
        result: {
          hits: [
            {
              _id: candidate.id,
              _score: candidate.score,
              fields: {
                ...candidate.metadata,
                text: candidate.text,
                ignored_index_field: "允许索引包含额外元数据",
              },
            },
          ],
        },
        usage: { readUnits: 1, embedTotalTokens: 10 },
      });
    const retriever = new PineconeStandardEvidenceRetriever(
      { searchRecords },
      "text",
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
    ).resolves.toEqual([
      { ...candidate, matched_terms: [], provider: "pinecone" },
    ]);

    expect(searchRecords).toHaveBeenCalledWith({
      query: {
        inputs: { text: "测试监测项适用什么规范" },
        topK: 3,
        filter: {
          evidence_kind: { $eq: "standard" },
          effective_status: { $eq: "active" },
          standard_version: { $in: ["demo-2026"] },
          monitoring_item: { $eq: "测试监测项" },
          excavation_safety_level: { $eq: "demo" },
          region: { $eq: "测试区域" },
        },
      },
      fields: [
        "text",
        "standard_name",
        "standard_version",
        "clause",
        "source_location",
        "applicability",
        "effective_status",
        "monitoring_item",
        "excavation_safety_level",
        "region",
      ],
    });
  });

  it("拒绝缺少规范版本的索引记录", async () => {
    const index: PineconeEvidenceIndex = {
      searchRecords: vi.fn().mockResolvedValue({
        result: {
          hits: [
            {
              _id: candidate.id,
              _score: candidate.score,
              fields: {
                ...candidate.metadata,
                standard_version: undefined,
                chunk_text: candidate.text,
              },
            },
          ],
        },
      }),
    };

    const retriever = new PineconeStandardEvidenceRetriever(index);
    await expect(retriever.search({ query: "测试" })).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });

  it("拒绝 Pinecone 非预期响应结构", async () => {
    const retriever = new PineconeStandardEvidenceRetriever({
      searchRecords: vi.fn().mockResolvedValue({
        result: { hits: null },
      }),
    });
    await expect(retriever.search({ query: "测试" })).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });

  it("查询失败时不暴露远端错误正文", async () => {
    const retriever = new PineconeStandardEvidenceRetriever({
      searchRecords: vi
        .fn()
        .mockRejectedValue(new Error("test-only-secret-canary")),
    });
    await expect(retriever.search({ query: "测试" })).rejects.toEqual(
      expect.objectContaining({
        code: "RETRIEVER_UNAVAILABLE",
        message: "Pinecone 规范证据检索暂不可用。",
      }),
    );
  });

  it("拒绝与来源元数据冲突的文本字段配置", () => {
    expect(
      () =>
        new PineconeStandardEvidenceRetriever(
          { searchRecords: vi.fn() },
          "standard_name",
        ),
    ).toThrow("Pinecone integrated embedding 文本字段配置不合法。");
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

  it("Pinecone 模式使用 integrated embedding，不要求注入查询向量函数", () => {
    vi.stubEnv("RAG_PROVIDER", "pinecone");
    const retriever = createStandardEvidenceRetriever({
      pineconeIndex: {
        searchRecords: vi.fn().mockResolvedValue({
          result: { hits: [] },
        }),
      },
    });
    expect(retriever.provider).toBe("pinecone");
  });

  it("Pinecone 模式仍需索引连接配置", () => {
    vi.stubEnv("RAG_PROVIDER", "pinecone");
    vi.stubEnv("PINECONE_API_KEY", "");
    expect(() => createStandardEvidenceRetriever()).toThrow(
      "pinecone 配置缺失或不合法。",
    );
  });
});
