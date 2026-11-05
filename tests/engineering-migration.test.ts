import { executeAgentRun } from "@/server/agents/executor";
import { dirname, resolve } from "node:path";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { adapterIdFromPayload, assertAdapterSnapshot, listEngineeringAdapters, loadEngineeringAdapter } from "@/server/engineering-adapters/registry";
import { runJudgement } from "@/server/skills/evaluate-thresholds/runner";
import { buildReportModelContext, validateNarrativeGrounding } from "@/server/agents/report-model";
import { reportNarrativeSchema } from "@/contracts/ai-report";
import { createStandardEvidenceRetriever } from "@/server/evidence/factory";
import { projectParameters } from "@/server/engineering-adapters/project";
import { legacyDirectory } from "@/server/auth/directory";
import { DEFAULT_PROJECT_ID } from "@/contracts/access";
import { GET, PUT } from "@/app/api/projects/current/engineering/route";
let root: string;
beforeEach(() => { root = mkdtempSync(join(tmpdir(), "engineering-migration-")); vi.stubEnv("EXCAVAGUARD_ACCESS_FILE", join(root,"access.json")); vi.stubEnv("EXCAVAGUARD_ACCESS_PASSWORD", ""); vi.stubEnv("EXCAVAGUARD_PROJECT_ID", DEFAULT_PROJECT_ID); });
afterEach(() => { vi.unstubAllEnvs(); rmSync(root, { recursive: true, force: true }); });
const id = "verification-monitoring";
const request = (body?: unknown) => new Request("http://localhost/api/projects/current/engineering", body ? { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
describe("跨场景通用入口与工程绑定", () => {
  it("同一计算Skill按适配器选择不同Python实现，不需要基坑参数", async () => {
    const result = await runJudgement({ adapterId: id, context: { segment: "SIM-A" }, records: [{ point_id: "SIM-A1", value: 3 }] });
    expect(result.trace?.fixture).toBe("SIMULATED_ONLY");
    expect(result.result).toMatchObject({ items: [{ current: 3, risk_level: "未知" }], project: { engineering_adapter: { id } } });
    const model = buildReportModelContext(result.result);
    expect(model.forms).toEqual(["M"]);
    expect(model.evidence_topics.join(" ")).toContain("验证测量");
    expect(adapterIdFromPayload(result.result)).toBe(id);
    expect(() => assertAdapterSnapshot(result.result)).not.toThrow();
    const paragraph = { text: "数据待核。", evidence_ids: [] };
    const narrative = reportNarrativeSchema.parse({ work_condition: paragraph, analysis: [paragraph], recommendations: [paragraph], limitations: [paragraph], appendix_analysis: [{ form: "M", analysis: paragraph, recommendation: paragraph }] });
    expect(() => validateNarrativeGrounding(narrative, model.facts, [], model.forms)).not.toThrow();
  });
  it("同一三Agent编排贯通非A–F模板及独立文件审计", async () => {
    const computed = await runJudgement({ adapterId: id, context: { segment: "SIM-A" }, records: [{ point_id: "SIM-A1", value: 3 }] });
    const execution = await executeAgentRun({ enginePayload: computed.result, reportMode: "template" });
    const draft = execution.state.report_draft;
    try {
      expect(draft?.artifacts).toHaveLength(3);
      expect(draft?.artifacts[0].sheets).toEqual(["M_验证测量"]);
      expect(execution.state.audit_result?.valid).toBe(true);
      expect(execution.state.audit_result?.stages?.semantic).toBe("not_required");
    } finally { if (draft?.artifacts[0]) rmSync(dirname(resolve(draft.artifacts[0].relative_path)), { recursive: true, force: true }); }
  });
  it("未配置独立RAG连接时拒绝，绝不退回基坑连接", () => {
    vi.stubEnv("EXCAVAGUARD_RAG_CONNECTIONS", "{}");
    expect(() => createStandardEvidenceRetriever({ adapterId: id })).toThrow("ADAPTER_RAG_NOT_CONFIGURED");
    vi.stubEnv("EXCAVAGUARD_RAG_CONNECTIONS", JSON.stringify({ "verification-only": { provider: "local", base_url: "http://127.0.0.1:8765" } }));
    expect(createStandardEvidenceRetriever({ adapterId: id }).provider).toBe("local");
  });
  it("生产环境不加载或展示测试场景", () => {
    vi.stubEnv("NODE_ENV", "production");
    expect(() => loadEngineeringAdapter(id)).toThrow("ENGINEERING_ADAPTER_UNSUPPORTED");
    expect(listEngineeringAdapters().some(adapter => adapter.id === id)).toBe(false);
  });
  it("项目绑定决定专业配置，跨场景请求参数不能替换已确认参数", async () => {
    const directory = legacyDirectory();
    directory.projects[0].engineering = { adapter_id: id, adapter_version: "1.0.0", parameters: { segment: "CONFIRMED" } };
    writeFileSync(join(root,"access.json"), JSON.stringify(directory));
    expect(projectParameters(DEFAULT_PROJECT_ID, { safety_level: "一级" }).context).toEqual({ segment: "CONFIRMED" });
    const read = await GET(request()).json();
    expect(read.adapter.id).toBe(id);
    const saved = await PUT(request({ expected_revision: 0, adapter_version: "1.0.0", parameters: { segment: "UPDATED" } }));
    expect(saved.status).toBe(200);
    expect(projectParameters(DEFAULT_PROJECT_ID, {}).context).toEqual({ segment: "UPDATED" });
    expect((await PUT(request({ expected_revision: 0, adapter_version: "1.0.0", parameters: { segment: "STALE" } }))).status).toBe(409);
  });
  it("可留空参数按缺失处理，不虚构数值", () => {
    expect(projectParameters(DEFAULT_PROJECT_ID, { safety_level: "一级", support_type: "地下连续墙" }).context).toMatchObject({ excavation_depth_m: null });
  });
  it("配置缺少专业关键参数或运行版本变化时阻断", async () => {
    await expect(runJudgement({ adapterId: id, context: {}, records: [{ value: 3 }] })).rejects.toThrow();
    const snapshot = loadEngineeringAdapter(id).snapshot;
    expect(() => assertAdapterSnapshot({ project: { engineering_adapter: { ...snapshot, digest: "0".repeat(64) } } })).toThrow("ADAPTER_VERSION_MISMATCH");
  });
});
