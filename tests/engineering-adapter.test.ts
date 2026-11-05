import { readFileSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { executeAgentRun } from "@/server/agents/executor";
import { describe, expect, it } from "vitest";
import { adapterAssetPath, loadEngineeringAdapter, validateEngineeringAdapter } from "@/server/engineering-adapters/registry";
import { runJudgement } from "@/server/skills/evaluate-thresholds/runner";
import { callSkillScript } from "@/server/skills/python-bridge";
import { readStandardCatalog } from "@/server/evidence/standard-catalog";
import { buildReportModelContext } from "@/server/agents/report-model";

const context = { safety_level: "一级" as const, support_type: "地下连续墙", excavation_depth_m: 20 };
const records = [
  { point_id: "SIM-ADAPTER-01", timestamp: "2026-10-01", metric: "wall_top_horizontal_displacement", value: 5, unit: "mm", data_origin: "simulated" },
  { point_id: "SIM-ADAPTER-01", timestamp: "2026-10-02", metric: "wall_top_horizontal_displacement", value: 27, unit: "mm", data_origin: "simulated" },
];
const manifest = () => JSON.parse(readFileSync(adapterAssetPath("engineering-adapters/foundation-pit/manifest.json"), "utf8"));
describe("基坑工程场景适配器", () => {
  it("校验真实资产并生成稳定指纹，核心字段无虚构默认值", () => {
    const first = loadEngineeringAdapter();
    expect(first.snapshot).toEqual(loadEngineeringAdapter().snapshot);
    expect(first.snapshot.digest).toMatch(/^[a-f0-9]{64}$/);
    expect(Object.keys(first.snapshot.asset_hashes).length).toBeGreaterThanOrEqual(20);
    expect(first.adapter.core_fields).toHaveLength(3);
    expect(first.adapter.core_fields.every(f => !("default" in f))).toBe(true);
  });
  it("拒绝未注册场景，包括规范目录入口", async () => {
    expect(() => loadEngineeringAdapter("tunnel")).toThrow("ENGINEERING_ADAPTER_UNSUPPORTED");
    expect(() => readStandardCatalog("tunnel")).toThrow("ENGINEERING_ADAPTER_UNSUPPORTED");
    await expect(runJudgement({ context, records, adapterId: "tunnel" })).rejects.toThrow("ENGINEERING_ADAPTER_UNSUPPORTED");
  });
  it("缺失资源、越界路径和不完整配置不能通过", () => {
    const invalid = manifest(); delete invalid.assets.calculator;
    expect(() => validateEngineeringAdapter(invalid)).toThrow();
    const missing = manifest(); missing.assets.calculator = "missing-calculator.py";
    expect(() => validateEngineeringAdapter(missing)).toThrow();
    expect(() => adapterAssetPath("/etc/passwd")).toThrow("ADAPTER_ASSET_OUTSIDE_ROOT");
    expect(() => adapterAssetPath("../../../../../../etc/passwd")).toThrow();
  });
  it("规范清单继续覆盖现有全部29本，不因适配器缩减", () => {
    const catalog = readStandardCatalog();
    expect(catalog).toHaveLength(29);
    expect(new Set(catalog.map(s => s.standard_version)).size).toBe(29);
  });
  it("同一输入适配前后计算、规则结果一致，并冻结适配器供Agent消费", async () => {
    const baseline = await callSkillScript("evaluate-thresholds", "run_judgement.py", {
      records, context, options: { with_payload: true, report_date: "2026-10-02" },
    });
    const actual = await runJudgement({ records, context, reportDate: "2026-10-02" });
    const old = baseline.result as Record<string, unknown>;
    const next = actual.result as Record<string, unknown>;
    expect(next.items).toEqual(old.items);
    expect(next.summary).toEqual(old.summary);
    expect(next.standards_sources).toEqual(old.standards_sources);
    expect((next.items as unknown[]).length).toBeGreaterThan(0);
    expect(next.project).toMatchObject({ engineering_adapter: { id: "foundation-pit", version: "2.2.0" } });
    expect(buildReportModelContext(next).engineering_adapter).toMatchObject({id:"foundation-pit",version:"2.2.0"});
  });
  it("缺少深度不自动补参，未知测项不套用基坑判据", async () => {
    const unknown = records.map(r => ({ ...r, metric: "unregistered_tunnel_metric" }));
    const actual = await runJudgement({ records: unknown, context: { ...context, excavation_depth_m: null }, reportDate: "2026-10-02" });
    expect((actual.result as { project: unknown }).project).toMatchObject({ excavation_depth_m: null });
    expect(JSON.stringify(actual.result)).toContain("UNKNOWN_METRIC");
  });
  it("适配器冻结载荷贯通真实Python编报与文件审计，不冒充语义审查", async () => {
    const computed = await runJudgement({ records, context, reportDate: "2026-10-02" });
    const execution = await executeAgentRun({ enginePayload: computed.result, reportMode: "template" });
    const draft = execution.state.report_draft;
    try {
      expect(draft?.artifacts).toHaveLength(3);
      expect(execution.state.audit_result?.valid).toBe(true);
      expect(execution.state.audit_result?.stages?.semantic).toBe("not_required");
      expect(execution.state.engine_snapshot.payload).toMatchObject({ project: { engineering_adapter: { id: "foundation-pit" } } });
    } finally {
      if (draft?.artifacts[0]) rmSync(dirname(resolve(draft.artifacts[0].relative_path)), { recursive: true, force: true });
    }
  });

});
