import { describe, expect, it, vi } from "vitest";
import type { StandardEvidence } from "@/contracts/standard-evidence";
import type { StandardEvidenceRetriever } from "@/server/evidence/retriever";
import { retrieveStandardEvidence } from "@/server/skills/retrieve-standard-evidence/runner";

const activeEvidence: StandardEvidence = {
  id: "std-demo-8.0.1",
  text: "仅用于自动化测试的规范条文候选内容，不代表真实工程要求。",
  metadata: {
    standard_name: "测试规范",
    standard_version: "DEMO-2026",
    clause: "8.0.1",
    source_location: "test-fixture#chunk=1",
    applicability: ["仅用于自动化测试"],
    effective_status: "active",
  },
  score: 0.92,
  matched_terms: [],
  provider: "pinecone",
};

function createRetriever(
  evidence: StandardEvidence[],
): StandardEvidenceRetriever {
  return {
    provider: "pinecone",
    search: vi.fn().mockResolvedValue(evidence),
  };
}

describe("retrieve-standard-evidence runner", () => {
  it("返回证据、人工复核提示和可追溯查询信息", async () => {
    const retriever = createRetriever([activeEvidence]);

    await expect(
      retrieveStandardEvidence(
        {
          query: "测试规范的适用条文",
          filters: { standard_versions: ["DEMO-2026"] },
          limit: 1,
        },
        { retriever },
      ),
    ).resolves.toEqual({
      status: "success",
      evidence: [activeEvidence],
      notice:
        "检索结果仅作为规范证据候选，适用性、版本有效性和工程使用须由专业工程师复核。",
      trace: {
        provider: "pinecone",
        query: "测试规范的适用条文",
        filters: {
          standard_versions: ["DEMO-2026"],
          effective_status: "active",
        },
        limit: 1,
        hit_count: 1,
        evidence_ids: ["std-demo-8.0.1"],
      },
    });

    expect(retriever.search).toHaveBeenCalledWith({
      query: "测试规范的适用条文",
      filters: {
        standard_versions: ["DEMO-2026"],
        effective_status: "active",
      },
      top_k: 1,
    });
  });

  it("空查询与无命中都主动弃权", async () => {
    await expect(
      retrieveStandardEvidence(
        { query: " ", limit: 3 },
        { retriever: createRetriever([]) },
      ),
    ).resolves.toMatchObject({
      status: "abstained",
      code: "INVALID_INPUT",
      evidence: [],
    });

    await expect(
      retrieveStandardEvidence(
        { query: "不存在的条文" },
        { retriever: createRetriever([]) },
      ),
    ).resolves.toMatchObject({
      status: "abstained",
      code: "EVIDENCE_NOT_FOUND",
      evidence: [],
      trace: { hit_count: 0, evidence_ids: [] },
    });
  });

  it("非现行或状态未知的结果不作为确定依据", async () => {
    const unknownEvidence: StandardEvidence = {
      ...activeEvidence,
      id: "std-demo-unknown",
      metadata: {
        ...activeEvidence.metadata,
        effective_status: "unknown",
      },
    };

    await expect(
      retrieveStandardEvidence(
        {
          query: "待核验条文",
          filters: { effective_status: "unknown" },
        },
        { retriever: createRetriever([unknownEvidence]) },
      ),
    ).resolves.toMatchObject({
      status: "abstained",
      code: "EVIDENCE_CONFLICT",
      evidence: [unknownEvidence],
      trace: {
        hit_count: 1,
        evidence_ids: ["std-demo-unknown"],
      },
    });
  });

  it("Provider 异常时不透传远端错误", async () => {
    const retriever: StandardEvidenceRetriever = {
      provider: "pinecone",
      search: vi.fn().mockRejectedValue(new Error("test-only-secret-canary")),
    };

    await expect(
      retrieveStandardEvidence({ query: "测试" }, { retriever }),
    ).resolves.toMatchObject({
      status: "abstained",
      code: "EVIDENCE_UNAVAILABLE",
      message: "规范证据检索失败，不能形成规范性结论。",
      evidence: [],
    });
  });
});
