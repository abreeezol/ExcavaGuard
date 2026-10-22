import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { executeAgentRun } from "@/server/agents/executor";
import { runJudgement } from "@/server/skills/evaluate-thresholds/runner";

// Explicitly opt in: invokes the configured model and RAG service; no simulated output.
const liveDescribe = process.env.EXCAVAGUARD_TEST_LLM === "1" ? describe : describe.skip;

liveDescribe("真实 LLM + RAG + 85 通道日报交付验收", () => {
  it("三个角色真实调用，完整日报与 A–F 通过两层审计", async () => {
    const python = resolve(".venv/bin/python");
    if (existsSync(python)) process.env.EXCAVAGUARD_PYTHON = python;
    const engine = await runJudgement({
      filePath: resolve("final_test/监测数据整合_7天_10分钟输入.xlsx"),
      reportDate: "2026-10-08",
      context: { safety_level: "一级", support_type: "地下连续墙", excavation_depth_m: 20 },
      project: { name: "最终宽表 AI 日报验收" },
    });
    const output = resolve("var/ai-live-acceptance");
    mkdirSync(output, { recursive: true });
    const execution = await executeAgentRun({
      enginePayload: engine.result, reportMode: "ai",
    }, {
      checkpoint: async (checkpoint) => {
        writeFileSync(resolve(output, "checkpoint.json"), JSON.stringify(checkpoint, null, 2));
      },
    });
    writeFileSync(resolve(output, "execution.json"), JSON.stringify(execution, null, 2));
    expect(execution.terminalAction.reason_code).toBe("AUDIT_PASSED");
    expect(execution.state.engine_snapshot.payload).toEqual(engine.result);
    expect(execution.state.audit_result?.valid).toBe(true);
    for (const role of ["supervisor", "report-delivery", "audit"]) {
      expect(execution.state.trace.some((event) =>
        event.capability === `llm-${role}` && event.status === "success",
      )).toBe(true);
    }
    expect(execution.state.evidence_snapshot?.evidence_ids.length).toBeGreaterThan(0);
    const draft = execution.state.report_draft!;
    const markdown = (draft.payload as { markdown: string }).markdown;
    expect(markdown).toContain("四、规范核对依据（RAG知识库检索）");
    expect(markdown).not.toContain("{{fact:");
    const sheets = draft.artifacts.find((artifact) => artifact.kind === "workbook")!.sheets;
    expect(sheets.filter((name) => /^附表[A-F]_/.test(name))).toHaveLength(6);
    console.info("已审计的真实 AI 日报：", draft.artifacts.map((artifact) => artifact.relative_path));
  }, 150_000);
});
