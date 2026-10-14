import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { beforeAll, describe, expect, it } from "vitest";

async function probePython(bin: string): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const done = (available: boolean) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(available);
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
  const localPython = resolve(process.cwd(), ".venv", "bin", "python");
  const candidates = [
    process.env.EXCAVAGUARD_PYTHON,
    process.env.PYTHON,
    existsSync(localPython) ? localPython : null,
    "python3",
    "python",
  ].filter((value): value is string => Boolean(value));
  for (const candidate of candidates) {
    if (await probePython(candidate)) return candidate;
  }
  return null;
})();

type NormalizeRunner =
  typeof import("@/server/skills/normalize-monitoring-data/runner");
type Json = Record<string, unknown>;

const describeWithPython = PYTHON ? describe : describe.skip;

describeWithPython("normalize-monitoring-data runner", () => {
  let runner: NormalizeRunner;

  beforeAll(async () => {
    process.env.EXCAVAGUARD_PYTHON = PYTHON as string;
    runner = await import("@/server/skills/normalize-monitoring-data/runner");
  });

  it("标准化原始观测并返回派生统计与轨迹", async () => {
    const envelope = await runner.normalizeMonitoringData({
      records: [
        {
          point_id: " p-01 ",
          timestamp: "2026-10-05 00:00:00",
          metric: "深层水平位移",
          value: 1,
          unit: "mm",
        },
        {
          point_id: " p-01 ",
          timestamp: "2026-10-06 00:00:00",
          metric: "深层水平位移",
          value: 3,
          unit: "mm",
        },
      ],
      includeRecords: true,
    });

    const result = envelope.result as Json;
    const records = result.records as Json[];
    expect(records).toHaveLength(2);
    expect(records[1]).toMatchObject({
      point_id: "P-01",
      metric_key: "deep_horizontal_displacement",
      baseline_value: 1,
      previous_value: 1,
      interval_days: 1,
    });
    expect(result.derived).toMatchObject({
      points: 1,
      series: 1,
      previous_derived: 1,
      interval_derived: 1,
    });
    expect(envelope.trace).toMatchObject({ source_records: 2, records: 2 });
  });

  it("累计量与非零基准冲突进入高严重度质量路径", async () => {
    const envelope = await runner.normalizeMonitoringData({
      records: [
        {
          point_id: "DP-01",
          timestamp: "2026-10-05",
          metric: "深层水平位移",
          value: 5,
          unit: "mm",
          measurement_semantics: "precomputed_cumulative",
          baseline_value: 100,
        },
      ],
      includeRecords: true,
    });
    const result = envelope.result as Json;
    const quality = result.quality_report as Json;
    expect(quality.by_code).toMatchObject({
      SEMANTIC_BASELINE_CONFLICT: 1,
    });
    expect((result.records as Json[])[0]).toMatchObject({
      baseline_value: 0,
      measurement_semantics: "precomputed_cumulative",
    });
  });

  it("拒绝非对象记录", async () => {
    await expect(
      runner.normalizeMonitoringData({ records: [null] }),
    ).rejects.toMatchObject({
      name: "EngineError",
      engineCode: "INVALID_INPUT",
    });
  });
});
