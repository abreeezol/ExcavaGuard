import { z } from "zod";

export const reportPeriodSchema = z.strictObject({
  type: z.enum(["weekly", "monthly", "custom"]),
  start_date: z.iso.date(),
  end_date: z.iso.date(),
}).superRefine((value, ctx) => {
  const start = Date.parse(`${value.start_date}T00:00:00Z`);
  const end = Date.parse(`${value.end_date}T00:00:00Z`);
  const days = (end - start) / 86_400_000 + 1;
  if (!Number.isInteger(days) || days < 1 || days > 366) {
    ctx.addIssue({ code: "custom", message: "区间需按起止日期有序填写，最多366天（含首尾日）。" });
  }
  if (value.type === "weekly" && days !== 7) {
    ctx.addIssue({ code: "custom", message: "周报需覆盖连续7天。" });
  }
  if (value.type === "monthly") {
    const last = new Date(end);
    last.setUTCDate(last.getUTCDate() + 1);
    if (!value.start_date.endsWith("-01") || value.start_date.slice(0, 7) !== value.end_date.slice(0, 7) || last.getUTCDate() !== 1) {
      ctx.addIssue({ code: "custom", message: "月报需覆盖完整自然月。" });
    }
  }
});

export type ReportPeriod = z.infer<typeof reportPeriodSchema>;
export type ReportKind = "daily" | ReportPeriod["type"];

export function presetReportPeriod(kind: "weekly" | "monthly", selectedDate: string): ReportPeriod {
  if (!z.iso.date().safeParse(selectedDate).success) throw new Error("请选择有效日期。");
  const end = new Date(`${selectedDate}T00:00:00Z`);
  if (!Number.isFinite(end.getTime())) throw new Error("请选择有效日期。");
  const start = new Date(end);
  if (kind === "weekly") start.setUTCDate(start.getUTCDate() - 6);
  else {
    start.setUTCDate(1);
    end.setUTCMonth(end.getUTCMonth() + 1, 0);
  }
  return reportPeriodSchema.parse({ type: kind, start_date: start.toISOString().slice(0, 10), end_date: end.toISOString().slice(0, 10) });
}
