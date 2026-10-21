import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { appendFileSync, existsSync, readFileSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
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
    const child = spawn(
      bin,
      ["-c", "import openpyxl; print(openpyxl.__version__)"],
      {
      stdio: ["ignore", "pipe", "pipe"],
      },
    );
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      done(false);
    }, 20_000);
    child.on("error", () => done(false));
    child.on("close", (code) => done(code === 0));
  });
}

const PYTHON = await (async () => {
  const localPython = resolve(process.cwd(), ".venv", "bin", "python");
  const candidates = [
    process.env.EXCAVAGUARD_PYTHON,
    process.env.PYTHON,
    existsSync(localPython) ? localPython : null,
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
const artifactDirectories = new Set<string>();

function trackArtifacts(draft: ReportDraft): ReportDraft {
  const first = draft.artifacts[0];
  if (first) {
    artifactDirectories.add(dirname(resolve(process.cwd(), first.relative_path)));
  }
  return draft;
}

async function overwriteWorkbookCell(
  workbookPath: string,
  sheetName: string,
): Promise<void> {
  await new Promise<void>((resolvePromise, rejectPromise) => {
    const child = spawn(
      PYTHON as string,
      [
        "-c",
        [
          "import openpyxl, sys",
          "path, sheet = sys.argv[1], sys.argv[2]",
          "wb = openpyxl.load_workbook(path)",
          "wb[sheet]['D6'] = 999",
          "wb.save(path)",
        ].join(";"),
        workbookPath,
        sheetName,
      ],
      { stdio: ["ignore", "pipe", "pipe"] },
    );
    let stderr = "";
    child.stderr.setEncoding("utf-8");
    child.stderr.on("data", (chunk: string) => (stderr += chunk));
    child.on("error", rejectPromise);
    child.on("close", (code) => {
      if (code === 0) resolvePromise();
      else rejectPromise(new Error(stderr || `Python exit ${code}`));
    });
  });
}

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
    measurement_semantics: "raw_observation",
    source_flags: [],
    source_metadata: {},
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

function dailyReportInputWithAllForms() {
  const payload = dailyReportInput();
  const source_flags = ["WIDE_FORMAT_EXPANDED"];
  const extraItems = [
    engineItem({
      point_id: "QN-01",
      metric_key: "wall_internal_force",
      metric_name: "围护墙内力",
      source_flags,
    }),
    engineItem({
      point_id: "ZL-01",
      metric_key: "support_axial_force",
      metric_name: "支撑轴力",
      source_flags,
    }),
    engineItem({
      point_id: "SW-01",
      metric_key: "groundwater_level",
      metric_name: "地下水位",
      source_flags,
    }),
    engineItem({
      point_id: "LF-01",
      metric_key: "crack_width_surface",
      metric_name: "地表裂缝",
      source_flags,
    }),
  ];
  const items = [...payload.items, ...extraItems];
  return {
    ...payload,
    context: {
      ...payload.context,
      real_records: items.length,
      records: items.length,
    },
    summary: {
      ...payload.summary,
      total: items.length,
      by_risk_level: { 报警: items.length - 1, 未知: 1 },
      by_data_origin: { real: items.length },
    },
    items,
  };
}

function engineSnapshot(): ArtifactEnvelope {
  return {
    ref: ref("excavaguard.daily_report_input/v1", "a"),
    payload: dailyReportInput(),
  };
}

function engineSnapshotWithAllForms(): ArtifactEnvelope {
  return {
    ref: ref("excavaguard.daily_report_input/v1", "d"),
    payload: dailyReportInputWithAllForms(),
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

  afterAll(() => {
    for (const directory of artifactDirectories) {
      rmSync(directory, { recursive: true, force: true });
    }
  });

  it("从冻结载荷生成带事实绑定和证据 ID 的草稿", async () => {
    const engine = engineSnapshot();
    const evidence = evidenceSnapshot();
    const rendered = await renderRunner.renderDailyReport({
      engineSnapshot: engine,
      evidenceSnapshot: evidence,
    });
    const draft = trackArtifacts(rendered.draft);
    const { trace } = rendered;

    expect(draft.ref.schema).toBe("excavaguard.report_draft/v1");
    expect(draft.fact_bindings.length).toBeGreaterThan(30);
    expect(draft.artifacts.map((artifact) => artifact.kind)).toEqual([
      "workbook",
      "cover_markdown",
      "appendices_markdown",
    ]);
    expect(
      draft.artifacts.every((artifact) =>
        existsSync(resolve(process.cwd(), artifact.relative_path)),
      ),
    ).toBe(true);
    expect(draft.artifact_bindings.length).toBeGreaterThan(20);
    expect(
      draft.artifacts.find((artifact) => artifact.kind === "workbook")?.sheets,
    ).toEqual(
      expect.arrayContaining([
        "监测日报",
        "附表A_水平位移监测日报表",
        "超限测点清单",
      ]),
    );
    expect(
      draft.artifacts
        .find((artifact) => artifact.kind === "workbook")
        ?.sheets.some((sheet) => sheet.startsWith("附表G")),
    ).toBe(false);
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
      artifact_binding_count: draft.artifact_bindings.length,
    });
  });

  it("独立审计通过未被修改的草稿", async () => {
    const engine = engineSnapshot();
    const evidence = evidenceSnapshot();
    const { draft: rawDraft } = await renderRunner.renderDailyReport({
      engineSnapshot: engine,
      evidenceSnapshot: evidence,
    });
    const draft = trackArtifacts(rawDraft);
    const { audit } = await validateRunner.validateReport({
      draft,
      engineSnapshot: engine,
      evidenceSnapshot: evidence,
    });

    expect(audit.issues, JSON.stringify(audit.issues, null, 2)).toEqual([]);
    expect(audit.valid).toBe(true);
    expect(audit.checks.every((check) => check.valid)).toBe(true);
    expect(audit.checks.map((check) => check.name)).toEqual(
      expect.arrayContaining([
        "exported-artifacts",
        "workbook-cell-bindings",
        "markdown-correspondence",
      ]),
    );
  });

  it("附表 C-F 前置监测日期和孔号，并以规范依据替代逐行来源标记", async () => {
    const engine = engineSnapshotWithAllForms();
    const rendered = await renderRunner.renderDailyReport({
      engineSnapshot: engine,
    });
    const draft = trackArtifacts(rendered.draft);
    const appendices = draft.artifacts.find(
      (artifact) => artifact.kind === "appendices_markdown",
    );
    expect(appendices).toBeDefined();
    const markdown = readFileSync(
      resolve(process.cwd(), appendices!.relative_path),
      "utf-8",
    );
    const coverMarkdown = String((draft.payload as { markdown: string }).markdown);
    const workCondition = coverMarkdown
      .split("## 一、工况描述\n")[1]
      ?.split("\n## 二、")[0];
    expect(workCondition).toBeDefined();
    expect(workCondition).toContain("规范依据：GB 50497-2019 表8.0.4");
    expect(workCondition).not.toContain("数据来源标记");
    const sheets = [
      ["附表C_围护墙内力等监测日报表", 2],
      ["附表D_支撑轴力等监测日报表", 3],
      ["附表E_地下水位等监测日报表", 4],
      ["附表F_裂缝监测日报表", 5],
    ] as const;
    for (const [sheet, itemIndex] of sheets) {
      const section = markdown
        .split(`## ${sheet}\n`)[1]
        ?.split("\n## ")[0];
      expect(section).toBeDefined();
      expect(section).toContain("| 监测日期 | 孔号(点号) |");
      expect(section).toContain("规范依据：GB 50497-2019 表8.0.4");
      expect(section).not.toContain("来源标记：");
      expect(draft.artifact_bindings).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            location: `${sheet}!A7`,
            fact_path: `items.${itemIndex}.timestamp`,
          }),
          expect.objectContaining({
            location: `${sheet}!B7`,
            fact_path: `items.${itemIndex}.point_id`,
          }),
        ]),
      );
    }
    const { audit } = await validateRunner.validateReport({
      draft,
      engineSnapshot: engine,
    });
    expect(audit.issues).toEqual([]);
    expect(audit.valid).toBe(true);
  });

  it("冻结 LLM 正文写入五节完整日报，与附表 Markdown 分离且独立重读审计通过", async () => {
    const engine = engineSnapshot();
    const evidence = evidenceSnapshot();
    const paragraph = (text: string) => ({ text, evidence_ids: ["std-gb50497-2019-8.0.4"] });
    const analysis: SupportingSnapshot = {
      status: "ready", evidence_ids: evidence.evidence_ids, gaps: [],
      artifact: {
        ref: ref("excavaguard.report_narrative/v1", "c"),
        payload: {
          schema: "excavaguard.report_narrative/v1",
          narrative: {
            work_condition: paragraph("工程处于 {{fact:project.excavation_stage}}，施工日志未提供。"),
            analysis: [paragraph("{{fact:items.0.point_id}} 累计变化 {{fact:items.0.cumulative}}，风险为 {{fact:items.0.risk_level}}。")],
            recommendations: [paragraph("建议工程师核验超限测点并结合现场情况复核。")],
            limitations: [paragraph("未知项缺本次观测值，应补齐资料后复核。")],
            appendix_analysis: [{ form: "A", analysis: paragraph("位移成果需关注超限与缺测。"), recommendation: paragraph("建议人工复测。") }],
          },
        },
      },
    };
    const rendered = await renderRunner.renderDailyReport({
      engineSnapshot: engine, evidenceSnapshot: evidence, analysisSnapshot: analysis,
    });
    const draft = trackArtifacts(rendered.draft);
    const payload = draft.payload as { markdown: string };
    for (const title of ["一、工况描述", "二、简要分析及判断性结论", "三、待复核事项", "四、规范核对依据（RAG知识库检索）", "五、签署"]) {
      expect(payload.markdown).toContain(title);
    }
    expect(payload.markdown).toContain("WTHD-01");
    expect(payload.markdown).toContain("仅用于测试的规范证据文本。");
    expect(payload.markdown).not.toContain("逐测点成果");
    expect(draft.fact_bindings.some((binding) => binding.binding_id.startsWith("narrative-fact-"))).toBe(true);
    const { audit } = await validateRunner.validateReport({
      draft, engineSnapshot: engine, evidenceSnapshot: evidence, analysisSnapshot: analysis,
    });
    expect(audit.issues).toEqual([]);
    expect(audit.valid).toBe(true);
  });

  it("报告数字被修改后审计阻断且不修改源事实", async () => {
    const engine = engineSnapshot();
    const evidence = evidenceSnapshot();
    const rendered = await renderRunner.renderDailyReport({
      engineSnapshot: engine,
      evidenceSnapshot: evidence,
    });
    trackArtifacts(rendered.draft);
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
    trackArtifacts(rendered.draft);
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

  it("附表 Markdown 被修改后审计同时检出文件哈希与内容不一致", async () => {
    const engine = engineSnapshot();
    const rendered = await renderRunner.renderDailyReport({
      engineSnapshot: engine,
    });
    const draft = trackArtifacts(rendered.draft);
    const markdown = draft.artifacts.find(
      (artifact) => artifact.kind === "appendices_markdown",
    );
    expect(markdown).toBeDefined();
    appendFileSync(
      resolve(process.cwd(), markdown!.relative_path),
      "\n未经绑定的修改\n",
      "utf-8",
    );

    const { audit } = await validateRunner.validateReport({
      draft,
      engineSnapshot: engine,
    });

    expect(audit.valid).toBe(false);
    expect(audit.issues.map((item) => item.code)).toEqual(
      expect.arrayContaining([
        "ARTIFACT_HASH_MISMATCH",
        "ARTIFACT_SIZE_MISMATCH",
        "MARKDOWN_CONTENT_MISMATCH",
      ]),
    );
  });

  it("Excel 事实单元格被修改后审计阻断", async () => {
    const engine = engineSnapshot();
    const rendered = await renderRunner.renderDailyReport({
      engineSnapshot: engine,
    });
    const draft = trackArtifacts(rendered.draft);
    const workbook = draft.artifacts.find(
      (artifact) => artifact.kind === "workbook",
    );
    expect(workbook).toBeDefined();
    await overwriteWorkbookCell(
      resolve(process.cwd(), workbook!.relative_path),
      "附表A_水平位移监测日报表",
    );

    const { audit } = await validateRunner.validateReport({
      draft,
      engineSnapshot: engine,
    });

    expect(audit.valid).toBe(false);
    expect(audit.issues.map((item) => item.code)).toEqual(
      expect.arrayContaining([
        "ARTIFACT_HASH_MISMATCH",
        "WORKBOOK_CELL_MISMATCH",
      ]),
    );
  });
});
