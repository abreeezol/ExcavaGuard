import { afterEach, describe, expect, it, vi } from "vitest";
import { createStandardEvidenceRetriever } from "@/server/evidence/factory";
import { retrieveStandardEvidence } from "@/server/skills/retrieve-standard-evidence/runner";

// Opt in after starting source/server.py. Normal CI never downloads or loads a model.
const liveDescribe =
  process.env.EXCAVAGUARD_TEST_LOCAL_RAG === "1" ? describe : describe.skip;

afterEach(() => {
  vi.unstubAllEnvs();
});

liveDescribe("真实 FastAPI → Next.js 本地规范证据接口", () => {
  function configure() {
    vi.stubEnv("RAG_PROVIDER", "local");
    vi.stubEnv("LOCAL_RAG_BASE_URL", "http://127.0.0.1:8600");
    vi.stubEnv("LOCAL_RAG_TIMEOUT_MS", "60000");
  }

  it("真实 BGE/Chroma 检索返回统一来源字段和稳定证据 ID", async () => {
    configure();
    const result = await retrieveStandardEvidence({
      query: "监测预警值应由基坑工程设计方确定",
      filters: { standard_versions: ["GB50497-2019"] },
      limit: 3,
    });
    expect(result.status).toBe("success");
    expect(result.trace.provider).toBe("local");
    expect(result.evidence).toHaveLength(3);
    for (const evidence of result.evidence) {
      expect(evidence.metadata.standard_version).toBe("GB50497-2019");
      expect(evidence.metadata.effective_status).toBe("active");
      expect(evidence.metadata.clause).not.toBe("");
      expect(evidence.metadata.source_location).toContain("#chunk=");
      expect(evidence.metadata.applicability.length).toBeGreaterThan(0);
      expect(evidence.provider).toBe("local");
      expect(result.trace.evidence_ids).toContain(evidence.id);
    }
  }, 60_000);

  it("不存在的规范版本返回无命中并由 Skill 弃权", async () => {
    configure();
    const result = await retrieveStandardEvidence({
      query: "监测预警值",
      filters: { standard_versions: ["TEST-NO-SUCH-STANDARD"] },
    });
    expect(result.status).toBe("abstained");
    expect(result.evidence).toEqual([]);
    expect(result.trace.hit_count).toBe(0);
  });

  it("未登记的工程适用条件不会被问题文本补造", async () => {
    configure();
    const retriever = createStandardEvidenceRetriever();
    await expect(retriever.search({
      query: "测试地区一级基坑监测要求",
      filters: { region: "测试未登记地区", excavation_safety_level: "一级" },
    })).resolves.toEqual([]);
  });
});
