import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

/**
 * 上传 → 分析 端到端测试（**需要 Python 引擎**）
 * ================================================
 *
 * 覆盖用户目标：
 *   「用户上传自己的数据后，可通过 Agent 完成确定性计算与风险识别，
 *     并标注所用规范；若同时上传了新规范，则按用户规范执行。」
 *
 * 找不到可用的 Python 解释器时整个 suite 跳过（不影响 `npm run check` 的其它用例）。
 *
 * 注意：探测必须用**异步** spawn。`spawnSync` 在部分受限/沙箱环境下会直接
 * 返回 `EBUSY`，会把"环境不支持同步 spawn"误判成"没有 Python"。
 */

async function probePython(bin: string): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const done = (ok: boolean) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(ok);
    };
    const child = spawn(bin, ["-c", "print('ok')"], { stdio: ["ignore", "pipe", "pipe"] });
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      done(false);
    }, 20_000);
    child.on("error", () => done(false));
    child.on("close", (code) => done(code === 0));
  });
}

const PYTHON = await (async () => {
  const candidates = [process.env.EXCAVAGUARD_PYTHON, process.env.PYTHON, "python3", "python"].filter(
    (value): value is string => Boolean(value && value.trim()),
  );
  for (const bin of candidates) {
    if (await probePython(bin)) return bin;
  }
  return null;
})();

const UPLOAD_ROOT = mkdtempSync(join(tmpdir(), "excavaguard-e2e-"));
const PROJECT_ID = "11111111-1111-4111-8111-111111111111";

// 存储根目录在调用时读取，模块作用域设置即可
process.env.EXCAVAGUARD_UPLOAD_ROOT = UPLOAD_ROOT;

const LEVEL_RANK: Record<string, number> = {
  正常: 0,
  关注: 1,
  预警: 2,
  报警: 3,
  危险报警: 4,
  未知: -1,
};

type Json = Record<string, unknown>;

const describeE2E = PYTHON ? describe : describe.skip;

describeE2E("上传 → 分析 端到端", () => {
  let uploadMonitoringPOST: (request: Request) => Promise<Response>;
  let runsPOST: (request: Request) => Promise<Response>;
  let standardsPOST: (request: Request) => Promise<Response>;
  let sampleGET: () => Response;

  let monitoringFileId = "";
  let standardFileId = "";

  beforeAll(async () => {
    // python-bridge 在模块加载时读取候选解释器，必须先设好环境再动态导入
    process.env.EXCAVAGUARD_PYTHON = PYTHON as string;
    ({ POST: uploadMonitoringPOST } = await import("@/app/api/monitoring-files/route"));
    ({ POST: runsPOST } = await import("@/app/api/runs/route"));
    ({ POST: standardsPOST } = await import("@/app/api/standards/route"));
    ({ GET: sampleGET } = await import("@/app/api/monitoring-files/sample/route"));
  });

  function jsonRequest(url: string, body: unknown) {
    return new Request(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  function runBody(overrides: Json = {}) {
    return {
      project_id: PROJECT_ID,
      monitoring_file_id: monitoringFileId,
      report_date: "2026-08-07",
      context: {
        safety_level: "一级",
        support_type: "地下连续墙",
        excavation_depth_m: 20,
      },
      ...overrides,
    };
  }

  it("示例 CSV 上传后立即返回解析报告", async () => {
    const bytes = new Uint8Array(await sampleGET().arrayBuffer());
    const form = new FormData();
    form.set("file", new File([bytes], "示例监测数据.csv", { type: "text/csv" }));

    const response = await uploadMonitoringPOST(
      new Request("http://localhost/api/monitoring-files", { method: "POST", body: form }),
    );
    expect(response.status).toBe(201);

    const body = (await response.json()) as Json;
    const file = body.file as Json;
    monitoringFileId = String(file.file_id);

    expect(file.kind).toBe("monitoring");
    expect(file.storage).toBe("local");
    expect(String(file.sha256)).toMatch(/^[0-9a-f]{64}$/);

    const report = body.read_report as Json;
    expect(report.ok).toBe(true);
    expect(report.encoding).toBe("utf-8-sig");
    expect(report.missing_required).toEqual([]);
    expect(report.data_rows).toBe(35); // 5 个测点 × 7 天
    expect(Object.values(report.mapped_columns as Json)).toContain("point_id");
    expect(Object.values(report.mapped_columns as Json)).toContain("direction");
  });

  it("原始观测表可直接算：不因缺 baseline/previous/interval 而全量弃权", async () => {
    const response = await runsPOST(
      jsonRequest("http://localhost/api/runs", runBody()),
    );
    expect(response.status).toBe(200);

    const body = (await response.json()) as Json;
    const payload = body.payload as Json;
    const summary = body.summary as Json;

    expect(payload.schema).toBe("excavaguard.daily_report_input/v1");
    expect((body.engine as Json).records).toBe(35);
    expect(summary.effective_standard_origin).toBe("default_library");

    // 派生标记：三项派生量确实被算出来并留痕
    const items = payload.items as Json[];
    const flags = new Set(items.flatMap((item) => (item.flags as string[]) ?? []));
    expect(flags.has("PREVIOUS_DERIVED")).toBe(true);
    expect(flags.has("INTERVAL_DERIVED")).toBe(true);

    // 默认规范库判据：WTHD-01 累计 60.8 mm 远超 20 mm
    const levels = summary.by_risk_level as Record<string, number>;
    expect(levels["危险报警"]).toBeGreaterThan(0);
    expect((payload.items as Json[])[0].evidence).toMatchObject({ standard: "GB 50497-2019" });
  });

  it("缺 H 时累计值弃权（不退回绝对量限值）并进入复核队列", async () => {
    const response = await runsPOST(
      jsonRequest(
        "http://localhost/api/runs",
        runBody({ context: { safety_level: "一级", support_type: "地下连续墙", excavation_depth_m: null } }),
      ),
    );
    expect(response.status).toBe(200);

    const body = (await response.json()) as Json;
    const summary = body.summary as Json;
    const payload = body.payload as Json;

    const abstain = summary.abstain as Record<string, number>;
    expect(abstain.MISSING_H).toBeGreaterThan(0);

    const reviewQueue = payload.review_queue as Json[];
    expect(reviewQueue.length).toBeGreaterThan(0);
    expect(reviewQueue.some((item) => ((item.abstain as string[]) ?? []).includes("MISSING_H"))).toBe(true);

    // 缺 H 不得被判为"正常"
    const flagged = (payload.items as Json[]).filter((item) =>
      ((item.abstain as string[]) ?? []).includes("MISSING_H"),
    );
    expect(flagged.length).toBeGreaterThan(0);
    expect(flagged.every((item) => item.risk_level !== "正常")).toBe(true);
  });

  it("上传宽松的用户规范 → 返回具体差异与默认值的条文依据", async () => {
    const payload = {
      source_id: "USER-E2E-2026",
      source_label: "XX企业基坑监测标准（E2E）",
      source_type: "user_uploaded",
      metrics: {
        wall_top_horizontal_displacement: {
          rules: [
            {
              rule_id: "WTHD-L1-PILE",
              safety_level: ["一级"],
              support_type: ["地下连续墙"],
              cumulative_mm: { min: 50, max: 60 },
              rate_mm_per_day: { min: 5, max: 6 },
              evidence: { standard: "XX企业基坑监测标准", clause: "5.2.1" },
            },
          ],
        },
      },
    };

    const response = await standardsPOST(
      jsonRequest("http://localhost/api/standards", {
        payload,
        context: { safety_level: "一级", support_type: "地下连续墙", excavation_depth_m: 20 },
      }),
    );
    expect(response.status).toBe(201);

    const body = (await response.json()) as Json;
    standardFileId = String((body.file as Json).file_id);

    const strictness = body.strictness as Json;
    expect(strictness.has_looser).toBe(true);
    expect(strictness.looser_count).toBe(2);

    // 反馈必须带默认值的规范名称与条文号
    const report = String(body.report);
    expect(report).toContain("GB 50497-2019");
    expect(report).toContain("表8.0.4");
    expect(report).toContain("放宽幅度");

    const looser = strictness.looser as Json[];
    expect(looser.every((item) => (item.default_evidence as Json).standard === "GB 50497-2019")).toBe(true);
  });

  it("使用用户规范后生效来源变为 user_uploaded，且至少一条判定被降级", async () => {
    const baselineResponse = await runsPOST(jsonRequest("http://localhost/api/runs", runBody()));
    const baseline = (await baselineResponse.json()) as Json;

    const withStandardResponse = await runsPOST(
      jsonRequest("http://localhost/api/runs", runBody({ standards_file_id: standardFileId })),
    );
    expect(withStandardResponse.status).toBe(200);
    const withStandard = (await withStandardResponse.json()) as Json;

    expect((withStandard.summary as Json).effective_standard_origin).toBe("user_uploaded");

    // 载荷里必须能看见"用户阈值比默认更宽松"的告警明细
    const payload = withStandard.payload as Json;
    const warnings = payload.standard_override_warnings as Json[];
    expect(warnings.length).toBeGreaterThan(0);
    const differences = warnings[0].differences as Json[];
    expect(differences.length).toBeGreaterThan(0);
    expect((differences[0].default_evidence as Json).standard).toBe("GB 50497-2019");

    // 同一份数据：放宽阈值后至少有一条判定等级下降（漏判风险的直接证据）
    const key = (item: Json) => `${item.point_id}|${item.timestamp}|${item.metric_key}`;
    const baseLevels = new Map(
      ((baseline.payload as Json).items as Json[]).map((item) => [key(item), String(item.risk_level)]),
    );
    const downgraded = ((payload.items as Json[]) ?? []).filter((item) => {
      const before = baseLevels.get(key(item));
      const after = String(item.risk_level);
      return before !== undefined && LEVEL_RANK[after] < LEVEL_RANK[before];
    });
    expect(downgraded.length).toBeGreaterThan(0);

    // 判定侧同样带宽松标记
    const looseFlagged = ((payload.items as Json[]) ?? []).filter((item) =>
      ((item.flags as string[]) ?? []).includes("USER_LIMIT_LOOSER_THAN_DEFAULT"),
    );
    expect(looseFlagged.length).toBeGreaterThan(0);
  });

  it("引用不存在的文件时明确 404", async () => {
    const response = await runsPOST(
      jsonRequest(
        "http://localhost/api/runs",
        runBody({ monitoring_file_id: "33333333-3333-4333-8333-333333333333" }),
      ),
    );
    expect(response.status).toBe(404);
  });
});

afterAll(() => {
  rmSync(UPLOAD_ROOT, { recursive: true, force: true });
});
