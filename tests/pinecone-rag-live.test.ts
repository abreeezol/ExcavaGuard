import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { executeAgentRun } from "@/server/agents/executor";
import type { ReportModelRequest } from "@/server/agents/report-model";
import type { StandardEvidence } from "@/contracts/standard-evidence";
import { runJudgement } from "@/server/skills/evaluate-thresholds/runner";
import type { PineconeStandardRecord } from "../tools/rag/standard-records";

// Uses real Pinecone reads and Python artifacts; model outputs are explicitly simulated.
const liveDescribe = process.env.EXCAVAGUARD_TEST_PINECONE === "1" ? describe : describe.skip;

liveDescribe("85 通道 AI 报告链：真实 Pinecone + 模拟模型 + 真实 Python 报告审计", () => {
  it("逐字段核对检索来源，产出完整日报和 A–F，保持全部冻结事实", async () => {
    const python = resolve(".venv/bin/python");
    if (existsSync(python)) process.env.EXCAVAGUARD_PYTHON = python;
    const source = new Map(
      readFileSync(resolve("var/rag/pinecone-records.jsonl"), "utf8")
        .trim().split("\n").map((line) => {
          const record = JSON.parse(line) as PineconeStandardRecord;
          return [record._id, record] as const;
        }),
    );
    const engine = await runJudgement({
      filePath: resolve("final_test/监测数据整合_7天_10分钟输入.xlsx"),
      reportDate: "2026-10-08",
      context: { safety_level: "一级", support_type: "地下连续墙", excavation_depth_m: 20 },
      project: { name: "AI链路验收（模型响应模拟）" },
    });
    const calls: string[] = [];
    const paragraph = (text: string) => ({ text, evidence_ids: [] });
    const execution = await executeAgentRun({
      enginePayload: engine.result, reportMode: "ai",
    }, {
      model: async (request: ReportModelRequest) => {
        calls.push(request.role);
        const context = request.context as { evidence_topics: string[]; forms: string[] };
        return {
          object: request.role === "supervisor"
            ? { focus_indices: [0], evidence_topics: context.evidence_topics }
            : request.role === "audit" ? { issues: [] } : {
              work_condition: paragraph("施工日志与巡视记录未提供，不能确认现场工况。"),
              analysis: [paragraph("本期整体风险为 {{fact:summary.overall_risk_level}}；存在未知项，必须补齐资料并复核。")],
              recommendations: [paragraph("建议工程师逐项核验超限、弃权及来源限制，并复核规范适用性。")],
              limitations: [paragraph("本文件为链路验收样例，模型文字使用模拟响应，不能用于模型质量验收。")],
              appendix_analysis: context.forms.map((form) => ({
                form, analysis: paragraph("成果与弃权原因见本表逐测点备注。"),
                recommendation: paragraph("建议工程师按冻结事实补充设计资料并复测。"),
              })),
            },
          model: "mock-for-chain-acceptance",
          usage: { input_tokens: 0, output_tokens: 0 },
        };
      },
    });
    const draft = execution.state.report_draft;
    try {
      expect(execution.terminalAction.reason_code).toBe("AUDIT_PASSED");
      expect(execution.state.engine_snapshot.payload).toEqual(engine.result);
      expect(calls).toEqual(["supervisor", "report-delivery", "audit"]);
      const evidence = (execution.state.evidence_snapshot?.artifact?.payload as {
        evidence: StandardEvidence[];
      }).evidence;
      expect(evidence.length).toBeGreaterThan(0);
      expect(evidence.some((item) => item.metadata.clause === "8.0.1")).toBe(true);
      for (const item of evidence) {
        const original = source.get(item.id)!;
        expect(original).toBeDefined();
        expect(item.text).toBe(original.chunk_text);
        for (const field of ["standard_name", "standard_version", "clause", "source_location",
          "applicability", "effective_status"] as const) {
          expect(item.metadata[field]).toEqual(original[field]);
        }
        expect(item.metadata.standard_version).toBe("GB50497-2019");
        expect(item.provider).toBe("pinecone");
        expect(item.metadata.effective_status).toBe("active");
      }
      const payload = draft!.payload as { markdown: string };
      expect(payload.markdown).toContain("四、规范核对依据（RAG知识库检索）");
      expect(payload.markdown).toContain("监测预警值应由基坑工程设计方确定");
      const sheets = draft!.artifacts.find((item) => item.kind === "workbook")!.sheets;
      expect(sheets.filter((name) => /^附表[A-F]_/.test(name))).toHaveLength(6);
      expect(sheets.some((name) => name.startsWith("附表G"))).toBe(false);
      console.info(JSON.stringify({
        evidence_count: evidence.length,
        rag_queries: execution.state.trace.filter((event) => event.capability === "retrieve-standard-evidence")
          .map((event) => ({ hits: event.output_versions.hit_count, gaps: event.return_reason })),
        model: "模拟响应，仅验证链路",
      }));
      if (process.env.EXCAVAGUARD_KEEP_AI_PREVIEW === "1") {
        const output = resolve("var/ai-acceptance");
        mkdirSync(output, { recursive: true });
        writeFileSync(resolve(output, "execution.json"), JSON.stringify(execution, null, 2));
      }
    } finally {
      if (draft && process.env.EXCAVAGUARD_KEEP_AI_PREVIEW !== "1") {
        rmSync(dirname(resolve(draft.artifacts[0].relative_path)), { recursive: true, force: true });
      }
    }
  }, 120_000);
});
