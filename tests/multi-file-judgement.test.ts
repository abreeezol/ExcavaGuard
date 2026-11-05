import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { runJudgement } from "@/server/skills/evaluate-thresholds/runner";

let root: string;
const context = { safety_level: "一级" as const, support_type: "地下连续墙", excavation_depth_m: 20 };
beforeEach(async () => { root = await mkdtemp(join(tmpdir(), "excavaguard-multiple-files-")); });
afterEach(async () => { await rm(root, { recursive: true, force: true }); });
async function files(first: string, second: string) {
  const paths = [join(root, "first.csv"), join(root, "second.csv")];
  await writeFile(paths[0], first);
  await writeFile(paths[1], second);
  return paths;
}

describe("多文件确定性输入协议", () => {
  it("长表CSV中的JSON来源信息在合并后保留区段和模拟标识", async () => {
    const header = "point_id,timestamp,metric_key,value,previous,interval_days,unit,data_origin,source_metadata\n";
    const row = (point: string, section: string) =>
      `${point},2026-10-10,wall_top_horizontal_displacement,27,23,1,mm,simulated,"{""section_id"":""${section}"",""sample_count"":8}"\n`;
    const filePaths = await files(header + row("SIMULATED-A", "A"), header + row("SIMULATED-B", "B"));
    const result = await runJudgement({ context, filePaths, reportDate: "2026-10-10" });
    const payload = result.result as { items: Array<Record<string, unknown>> };
    expect(payload.items).toHaveLength(2);
    expect(payload.items.every(item => item.unit === "mm")).toBe(true);
    expect((result.result as { project: unknown }).project).toMatchObject(context);
    expect(payload.items.map(item => item.data_origin)).toEqual(["simulated", "simulated"]);
    expect(JSON.stringify(result)).toContain('"section_id":"A"');
    expect(JSON.stringify(result)).toContain('"section_id":"B"');
    expect(JSON.stringify(result)).toContain('"collaboration_source_position":2');
  });

  it("归一化观测单位不覆盖来源聚合统计的原单位", async () => {
    const header = "point_id,timestamp,metric_key,value,unit,source_metadata\n";
    const row = (point: string) => `${point},2026-10-10,wall_top_horizontal_displacement,2.7,cm,"{""daily_aggregation"":{""minimum"":2,""maximum"":3.5}}"\n`;
    const filePaths = await files(header + row("SIM-A"), header + row("SIM-B"));
    const result = await runJudgement({ context, filePaths, reportDate: "2026-10-10" });
    const payload = result.result as { items: Array<Record<string, unknown>> };
    expect(payload.items[0]).toMatchObject({ current: 27, unit: "mm", source_metadata: { daily_aggregation: { maximum: 3.5, unit: "cm" } } });
  });

  it("宽表跨文件先合并，再选择当日末值；保留日内样本数与累计量零基准", async () => {
    const header = "时间,深层水平位移-SIMULATED-P-累计值(mm)\n";
    const filePaths = await files(
      header + "2026-10-01 08:00:00,3\n2026-10-02 08:00:00,5\n",
      header + "2026-10-02 20:00:00,7\n2026-10-03 08:00:00,90\n",
    );
    const result = await runJudgement({ context, filePaths, reportDate: "2026-10-02" });
    const payload = result.result as { items: Array<Record<string, unknown>> };
    expect(payload.items).toHaveLength(1);
    expect(payload.items[0]).toMatchObject({ current: 7, baseline: 0, previous: 3, cumulative: 7, single_change: 4 });
    expect(result.trace).toMatchObject({ source_records: 4, records: 2 });
    const aggregation = result.trace?.daily_aggregation as { output_records: number };
    expect(aggregation.output_records).toBe(2);
  });

  it("量值语义冲突和文件协议混用必须拒绝", async () => {
    const filePaths = await files(
      "point_id,timestamp,metric_key,value,unit,measurement_semantics\nSIMULATED-P,2026-10-01,wall_top_horizontal_displacement,3,mm,raw_observation\n",
      "point_id,timestamp,metric_key,value,unit,measurement_semantics\nSIMULATED-P,2026-10-02,wall_top_horizontal_displacement,5,mm,precomputed_cumulative\n",
    );
    await expect(runJudgement({ context, filePaths, reportDate: "2026-10-02" }))
      .rejects.toMatchObject({ engineCode: "DATA_QUALITY" });
    await expect(runJudgement({ context, filePaths, filePath: filePaths[0] }))
      .rejects.toMatchObject({ engineCode: "INVALID_INPUT" });
  });
});
