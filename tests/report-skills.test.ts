import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { beforeAll, describe, expect, it } from "vitest";
import type {
  ArtifactEnvelope,
  ReportDraft,
  SupportingSnapshot,
} from "@/contracts/agent-runtime";

async function probePython(bin: string): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const done = (ok: boolean) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(ok);
    };
    const child = spawn(bin, ["-c", "print('ok')"], {
      stdio: ["ignore", "pipe", "pipe"],
    });
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      done(false);
    }, 20_000);
    child.on("error", () => done(false));
    child.on("close", (code) => done(code === 0));
  });
}

const PYTHON = await (async () => {
  const candidates = [
    process.env.EXCAVAGUARD_PYTHON,
    process.env.PYTHON,
    "python3",
    "python",
  ].filter((value): value is string => Boolean(value && value.trim()));
  for (const bin of candidates) {
    if (await probePython(bin)) return bin;
  }
  return null;
})();

type RenderRunner = typeof import("@/server/skills/render-daily-report/runner");
type ValidateRunner = typeof import("@/server/skills/validate-report/runner");

const describeWithPython = PYTHON ? describe : describe.skip;

function ref(schema: string, hashChar: string) {
  return {
    artifact_id: randomUUID(),
    schema,
    version: 1,
    content_hash: hashChar.repeat(64),
  };
}

function engineItem(overrides: Record<string, unknown> = {}) {
  return {
    point_id: "WTHD-01",
    point_name: "墙顶水平位移监测点 1",
    point_type: "墙顶位移",
    metric_key: "wall_top_horizontal_displacement",
    metric_name: "围护墙顶部水平位移",
    timestamp: "2026-10-13T08:00:00+08:00",
    data_origin: "real",
    baseline: 0,
    previous: 18,
    current: 22,
    interval_days: 1,
    cumulative: 22,
    single_change: 4,
    rate: 4,
    slope: 3.2,
    problem_category: "变形过大",
    risk_level: "报警",
    utilization: 1.1,
    checks: [
      {
        type: "cumulative",
        value: 22,
        limit: 20,
        unit: "mm",
        verdict: "exceeded",
      },
    ],
    effective_standard: {
      origin: "default_library",
      source_label: "GB 50497-2019",
      rule_id: "WTHD-L1-PILE",
    },
    rule_id: "WTHD-L1-PILE",
    evidence: {
      standard: "GB 50497-2019",
      clause: "表8.0.4",
      note: "测试固定样例",
    },
    abstain: [],
    abstain_reasons: [],
    flags: [],
    needs_review: false,
    ...overrides,
  };
}

function dailyReportInput() {
  const alert = engineItem();
  const review = engineItem({
    point_id: "WTHD-02",
    point_name: "墙顶水平位移监测点 2",
    current: null,
    cumulative: null,
    single_change: null,
    rate: null,
    risk_level: "未知",
    utilization: null,
    checks: [],
    rule_id: null,
    evidence: {},
    abstain: ["MISSING_CURRENT"],
    abstain_reasons: ["缺少本次观测值"],
    needs_review: true,
  });
  return {
    schema: "excavaguard.daily_report_input/v1",
    contract: {
      producer: "test",
      consumer: "render-daily-report",
      stability: "fields-add-only",
      schema_file: "contracts/daily_report_input.schema.json",
      excludes: ["正式签发"],
    },
    generated_from: {
      stage1: "阶段一 · 数据准备",
      stage2: "阶段二 · 确定性计算",
      stage3: "阶段三 · 规范比对",
    },
    project: {
      name: "测试基坑工程",
      monitoring_unit: "测试监测单位",
      report_date: "2026-10-13",
      excavation_stage: "开挖至第二道支撑下方",
      excavation_depth_m: 12,
      safety_level: "一级",
      support_type: "地下连续墙",
    },
    context: {
      real_records: 2,
      simulated_records: 0,
      records: 2,
      effective_standard_origin: "default_library",
      effective_standard_stage: "阶段三 · 规范比对",
      real_is_primary: true,
      simulated_note: "无模拟数据。",
    },
    standards_sources: [{ source_id: "GB50497-2019" }],
    data_quality: {
      issue_count: 1,
      by_code: { MISSING_VALUE: 1 },
      blocked_records: 1,
    },
    summary: {
      total: 2,
      by_risk_level: { 报警: 1, 未知: 1 },
      by_problem_category: { 变形过大: 1, 数据质量异常: 1 },
      by_data_origin: { real: 2 },
      abstain: { MISSING_CURRENT: 1 },
      overall_risk_level: "报警",
    },
    alerts: [alert],
    review_queue: [review],
    standard_override_warnings: [],
    items: [alert, review],
    disclaimer: "本结果仅供工程师复核，不替代正式预警、审核或签发。",
    note: "测试载荷。",
  };
}

function engineSnapshot(): ArtifactEnvelope {
  return {
    ref: ref("excavaguard.daily_report_input/v1", "a"),
    payload: dailyReportInput(),
  };
}

function evidenceSnapshot(): SupportingSnapshot {
  return {
    status: "ready",
    artifact: {
      ref: ref("excavaguard.standard_evidence/v1", "b"),
      payload: {
        status: "success",
        evidence: [
          {
            id: "std-gb50497-2019-8.0.4",
            text: "仅用于测试的规范证据文本。",
            metadata: {
              standard_name: "建筑基坑工程监测技术标准",
              standard_version: "GB 50497-2019",
              clause: "表8.0.4",
              source_location: "测试来源",
              applicability: ["测试"],
              effective_status: "active",
            },
            score: 0.9,
            matched_terms: ["水平位移"],
            provider: "pinecone",
          },
        ],
      },
    },
    evidence_ids: ["std-gb50497-2019-8.0.4"],
    gaps: [],
  };
}

describeWithPython("报告交付与独立审计 Skill", () => {
  let renderRunner: RenderRunner;
  let validateRunner: ValidateRunner;

  beforeAll(async () => {
    process.env.EXCAVAGUARD_PYTHON = PYTHON as string;
    renderRunner = await import("@/server/skills/render-daily-report/runner");
    validateRunner = await import("@/server/skills/validate-report/runner");
  });

  it("从冻结载荷生成带事实绑定和证据 ID 的草稿", async () => {
    const engine = engineSnapshot();
    const evidence = evidenceSnapshot();
    const { draft, trace } = await renderRunner.renderDailyReport({
      engineSnapshot: engine,
      evidenceSnapshot: evidence,
    });

    expect(draft.ref.schema).toBe("excavaguard.report_draft/v1");
    expect(draft.fact_bindings.length).toBeGreaterThan(30);
    expect(draft.citations).toEqual([
      expect.objectContaining({
        evidence_id: "std-gb50497-2019-8.0.4",
      }),
    ]);
    expect(draft.payload).toMatchObject({
      status: "draft",
      review_required: true,
      sections: {
        summary: { overall_risk_level: "报警" },
      },
    });
    expect(String((draft.payload as { markdown: string }).markdown)).toContain(
      "测试基坑工程监测日报（草稿）",
    );
    expect(trace).toMatchObject({
      calculation_performed: false,
      risk_reclassified: false,
    });
  });

  it("独立审计通过未被修改的草稿", async () => {
    const engine = engineSnapshot();
    const evidence = evidenceSnapshot();
    const { draft } = await renderRunner.renderDailyReport({
      engineSnapshot: engine,
      evidenceSnapshot: evidence,
    });
    const { audit } = await validateRunner.validateReport({
      draft,
      engineSnapshot: engine,
      evidenceSnapshot: evidence,
    });

    expect(audit.valid).toBe(true);
    expect(audit.issues).toEqual([]);
    expect(audit.checks.every((check) => check.valid)).toBe(true);
  });

  it("报告数字被修改后审计阻断且不修改源事实", async () => {
    const engine = engineSnapshot();
    const evidence = evidenceSnapshot();
    const rendered = await renderRunner.renderDailyReport({
      engineSnapshot: engine,
      evidenceSnapshot: evidence,
    });
    const draft = structuredClone(rendered.draft) as ReportDraft;
    (
      draft.payload as {
        sections: { monitoring_results: { items: Array<{ current: number }> } };
      }
    ).sections.monitoring_results.items[0].current = 999;

    const { audit } = await validateRunner.validateReport({
      draft,
      engineSnapshot: engine,
      evidenceSnapshot: evidence,
    });

    expect(audit.valid).toBe(false);
    expect(audit.issues.map((item) => item.code)).toEqual(
      expect.arrayContaining([
        "REPORT_CONTENT_MISMATCH",
        "FACT_VALUE_MISMATCH",
      ]),
    );
    expect(
      (engine.payload as ReturnType<typeof dailyReportInput>).items[0].current,
    ).toBe(22);
  });

  it("草稿自报未批准模板版本时审计阻断", async () => {
    const engine = engineSnapshot();
    const rendered = await renderRunner.renderDailyReport({
      engineSnapshot: engine,
    });
    const draft = structuredClone(rendered.draft) as ReportDraft;
    (draft.payload as { template_version: string }).template_version =
      "unapproved-template/v1";

    const { audit } = await validateRunner.validateReport({
      draft,
      engineSnapshot: engine,
    });

    expect(audit.valid).toBe(false);
    expect(audit.issues.map((item) => item.code)).toContain(
      "REPORT_CONTENT_MISMATCH",
    );
  });
});
