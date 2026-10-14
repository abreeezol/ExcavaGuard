import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

async function probeExcelPython(bin: string): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const done = (available: boolean) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(available);
    };
    const child = spawn(bin, ["-c", "import openpyxl; print(openpyxl.__version__)"], {
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

const EXCEL_PYTHON = await (async () => {
  const local = join(process.cwd(), ".venv", "bin", "python");
  const candidates = [
    process.env.EXCAVAGUARD_PYTHON,
    process.env.PYTHON,
    existsSync(local) ? local : null,
    "python3",
    "python",
  ].filter((value): value is string => Boolean(value));
  for (const candidate of candidates) {
    if (await probeExcelPython(candidate)) return candidate;
  }
  return null;
})();

const describeWithExcel = EXCEL_PYTHON ? describe : describe.skip;
const uploadRoot = mkdtempSync(join(tmpdir(), "excavaguard-wide-e2e-"));
process.env.EXCAVAGUARD_UPLOAD_ROOT = uploadRoot;

type Json = Record<string, unknown>;

describeWithExcel("最终混合宽表上传与分析", () => {
  let uploadPOST: (request: Request) => Promise<Response>;
  let runsPOST: (request: Request) => Promise<Response>;
  let artifactGET: (
    request: Request,
    context: { params: Promise<{ draftId: string; fileName: string }> },
  ) => Promise<Response>;
  const artifactDirectories = new Set<string>();

  beforeAll(async () => {
    process.env.EXCAVAGUARD_PYTHON = EXCEL_PYTHON as string;
    ({ POST: uploadPOST } = await import("@/app/api/monitoring-files/route"));
    ({ POST: runsPOST } = await import("@/app/api/runs/route"));
    ({ GET: artifactGET } = await import(
      "@/app/api/report-artifacts/[draftId]/[fileName]/route"
    ));
  });

  afterAll(() => {
    rmSync(uploadRoot, { recursive: true, force: true });
    for (const directory of artifactDirectories) {
      rmSync(directory, { recursive: true, force: true });
    }
  });

  it(
    "识别 85 通道并按报告日聚合，累计量不按窗口首值重新归零",
    async () => {
      const workbook = readFileSync(
        join(process.cwd(), "final_test", "监测数据整合_7天_10分钟.xlsx"),
      );
      const form = new FormData();
      form.set(
        "file",
        new File([workbook], "监测数据整合_7天_10分钟.xlsx", {
          type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }),
      );

      const uploadResponse = await uploadPOST(
        new Request("http://localhost/api/monitoring-files", {
          method: "POST",
          body: form,
        }),
      );
      expect(uploadResponse.status).toBe(201);
      const upload = (await uploadResponse.json()) as Json;
      const readReport = upload.read_report as Json;
      expect(readReport).toMatchObject({
        ok: true,
        layout: "wide",
        data_rows: 1008,
        channel_count: 85,
        expanded_records: 85_680,
      });
      expect(readReport.source_flags).toEqual(
        expect.arrayContaining([
          "SOURCE_TIME_ALIGNED",
          "SOURCE_RESAMPLED",
          "SOURCE_LINEAR_INTERPOLATION_PRESENT",
          "SOURCE_END_VALUE_HOLD_PRESENT",
        ]),
      );

      const fileId = String((upload.file as Json).file_id);
      const runResponse = await runsPOST(
        new Request("http://localhost/api/runs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: "22222222-2222-4222-8222-222222222222",
            monitoring_file_id: fileId,
            report_date: "2026-10-08",
            context: {
              safety_level: "一级",
              support_type: "地下连续墙",
              excavation_depth_m: 20,
            },
            project: { name: "最终宽表验收" },
            options: { generate_report: true },
          }),
        }),
      );
      expect(runResponse.status).toBe(200);

      const run = (await runResponse.json()) as Json;
      expect(run.engine).toMatchObject({
        records: 340,
        source_records: 85_680,
      });
      const aggregation = (run.engine as Json).daily_aggregation as Json;
      expect(aggregation).toMatchObject({
        channels: 85,
        output_records: 340,
        report_date: "2026-10-08",
      });

      const items = ((run.payload as Json).items ?? []) as Json[];
      expect(items).toHaveLength(85);
      expect((run.payload as Json).context).toMatchObject({
        records: 85,
        history_records: 340,
        item_date: "2026-10-08",
      });
      expect(
        items.every((item) => String(item.timestamp).startsWith("2026-10-08")),
      ).toBe(true);
      const cumulative = items.find(
        (item) =>
          item.point_id === "B-DP-01" &&
          String(item.timestamp).startsWith("2026-10-08"),
      );
      expect(cumulative).toMatchObject({
        measurement_semantics: "precomputed_cumulative",
        baseline: 0,
      });
      expect(cumulative?.cumulative).toBe(cumulative?.current);
      expect(cumulative?.source_flags).toEqual(
        expect.arrayContaining(["DAILY_END_AGGREGATED"]),
      );

      const crackItems = items.filter((item) => item.point_id === "LF-01");
      expect(new Set(crackItems.map((item) => item.metric_key))).toEqual(
        new Set(["裂缝长度", "裂缝宽度"]),
      );
      expect(crackItems.every((item) => item.risk_level === "未知")).toBe(true);
      expect(
        crackItems.every((item) =>
          ((item.abstain as string[]) ?? []).includes("UNKNOWN_METRIC"),
        ),
      ).toBe(true);

      const agentRun = run.agent_run as Json;
      const state = agentRun.state as Json;
      const reportDraft = state.report_draft as Json;
      const audit = state.audit_result as Json;
      expect(state.run).toMatchObject({
        run_id: run.run_id,
        status: "awaiting_human_review",
        current_stage: "human_review",
      });
      expect(agentRun.terminal_action).toMatchObject({
        type: "handoff_to_human",
        reason_code: "AUDIT_PASSED",
      });
      expect(agentRun.steps).toBe(3);
      expect(audit).toMatchObject({ valid: true, issues: [] });
      const artifacts = reportDraft.artifacts as Json[];
      artifactDirectories.add(
        dirname(
          resolve(
            process.cwd(),
            String(artifacts[0].relative_path),
          ),
        ),
      );
      const reportWorkbook = artifacts.find(
        (artifact) => artifact.kind === "workbook",
      );
      expect(reportWorkbook?.sheets as string[]).toEqual(
        expect.arrayContaining([
          "监测日报",
          "附表A_水平位移监测日报表",
          "附表B_深层水平位移监测日报表",
          "附表C_围护墙内力等监测日报表",
          "附表D_支撑轴力等监测日报表",
          "附表E_地下水位等监测日报表",
          "附表F_裂缝监测日报表",
          "超限测点清单",
          "待复核事项",
          "来源说明",
        ]),
      );
      expect(
        (reportWorkbook?.sheets as string[]).some((sheet) =>
          sheet.startsWith("附表G"),
        ),
      ).toBe(false);
      const downloads = agentRun.downloads as Json[];
      expect(downloads).toHaveLength(3);
      const workbookDownload = downloads.find(
        (download) => download.kind === "workbook",
      );
      const downloadResponse = await artifactGET(
        new Request(`http://localhost${String(workbookDownload?.url)}`),
        {
          params: Promise.resolve({
            draftId: String((reportDraft.ref as Json).artifact_id),
            fileName: String(workbookDownload?.file_name),
          }),
        },
      );
      expect(downloadResponse.status).toBe(200);
      expect(downloadResponse.headers.get("content-type")).toBe(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      );
      expect((await downloadResponse.arrayBuffer()).byteLength).toBe(
        workbookDownload?.size_bytes,
      );

      const traversalResponse = await artifactGET(
        new Request("http://localhost/api/report-artifacts/invalid"),
        {
          params: Promise.resolve({
            draftId: String((reportDraft.ref as Json).artifact_id),
            fileName: "../监测日报_2026-10-08_草稿.xlsx",
          }),
        },
      );
      expect(traversalResponse.status).toBe(400);
    },
    45_000,
  );
});
