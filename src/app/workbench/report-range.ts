import { z } from "zod";
import { presetReportPeriod, reportPeriodSchema, type ReportKind } from "@/contracts/report-period";
import type { RunSummary } from "@/contracts/runs";

export type ReportRange = { kind: ReportKind; date: string; start: string; end: string };

export function resolveReportRange(range: ReportRange) {
  if (range.kind === "daily") {
    return { report_date: z.iso.date().parse(range.date), report_period: undefined };
  }
  const period = range.kind === "custom"
    ? reportPeriodSchema.parse({ type: "custom", start_date: range.start, end_date: range.end })
    : presetReportPeriod(range.kind, range.date);
  return { report_date: period.end_date, report_period: period };
}

export function reportRangeLabel(range: ReportRange): string {
  const resolved = resolveReportRange(range);
  const labels = { daily: "日报", weekly: "周报", monthly: "月报", custom: "自定义报告" };
  return `${labels[range.kind]} · ${resolved.report_period
    ? `${resolved.report_period.start_date} 至 ${resolved.report_period.end_date}` : resolved.report_date}`;
}

export function latestSuccessfulRun(runs: RunSummary[]): RunSummary | undefined {
  return runs.filter(run => run.execution_status === "completed" && !run.error)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
}
