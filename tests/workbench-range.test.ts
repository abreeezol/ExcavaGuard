import { describe, expect, it } from "vitest";
import type { RunSummary } from "@/contracts/runs";
import { latestSuccessfulRun, reportRangeLabel, resolveReportRange } from "@/app/workbench/report-range";

describe("工作台范围确认合同", () => {
  it("日报不传周期，并拒绝未确认的空日期", () => {
    expect(resolveReportRange({ kind: "daily", date: "2026-11-04", start: "", end: "" }))
      .toEqual({ report_date: "2026-11-04", report_period: undefined });
    expect(() => resolveReportRange({ kind: "daily", date: "", start: "", end: "" })).toThrow();
  });
  it("周报跨年时仍含结束日及之前6日", () => {
    expect(resolveReportRange({ kind: "weekly", date: "2027-01-03", start: "", end: "" }))
      .toEqual({ report_date: "2027-01-03", report_period: {
        type: "weekly", start_date: "2026-12-28", end_date: "2027-01-03",
      } });
  });
  it("月份选择转为完整自然月，并支持闰年二月", () => {
    expect(resolveReportRange({ kind: "monthly", date: "2028-02-01", start: "", end: "" }))
      .toEqual({ report_date: "2028-02-29", report_period: {
        type: "monthly", start_date: "2028-02-01", end_date: "2028-02-29",
      } });
    expect(reportRangeLabel({ kind: "monthly", date: "2026-02-01", start: "", end: "" }))
      .toBe("月报 · 2026-02-01 至 2026-02-28");
  });
  it("历史自定义范围可以恢复，拒绝倒序及超过366天", () => {
    expect(resolveReportRange({ kind: "custom", date: "", start: "2026-10-20", end: "2026-11-04" }))
      .toEqual({ report_date: "2026-11-04", report_period: {
        type: "custom", start_date: "2026-10-20", end_date: "2026-11-04",
      } });
    expect(() => resolveReportRange({ kind: "custom", date: "", start: "2026-11-04", end: "2026-10-20" })).toThrow();
    expect(() => resolveReportRange({ kind: "custom", date: "", start: "2025-01-01", end: "2026-11-04" })).toThrow();
  });
});

describe("默认报告候选", () => {
  const run = (id: string, created: string, overrides: Partial<RunSummary> = {}): RunSummary => ({
    run_id: id, revision: 1, created_at: created, updated_at: created,
    execution_status: "completed", error: null, report_date: "2026-11-04", project_name: "测试工程",
    agent_status: "awaiting_human_review", decision: null, parent_run_id: null, ...overrides,
  });
  it("按创建时间而非报告日或输入顺序，选最近无错误的成功候选", () => {
    const runs = [
      run("older", "2026-11-01T00:00:00Z", { report_date: "2026-12-01" }),
      run("failed", "2026-11-04T00:00:00Z", { execution_status: "failed" }),
      run("latest", "2026-11-03T00:00:00Z"),
      run("error", "2026-11-05T00:00:00Z", { error: { code: "FAILED", message: "失败" } }),
    ];
    expect(latestSuccessfulRun(runs)?.run_id).toBe("latest");
    expect(runs[0].run_id).toBe("older");
  });
  it("没有成功候选时不创建样例结果", () => {
    expect(latestSuccessfulRun([])).toBeUndefined();
    expect(latestSuccessfulRun([run("waiting", "2026-11-04T00:00:00Z", { execution_status: "waiting" })])).toBeUndefined();
  });
});
