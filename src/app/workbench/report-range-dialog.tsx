"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import type { ReportKind } from "@/contracts/report-period";
import { reportRangeLabel, resolveReportRange, type ReportRange } from "./report-range";

export function ReportRangeDialog({ initial, onConfirm, onClose }: {
  initial: ReportRange | null;
  onConfirm: (range: ReportRange) => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [kind, setKind] = useState<ReportKind>(initial?.kind ?? "daily");
  const [date, setDate] = useState(initial?.date ?? "");
  const [month, setMonth] = useState(initial?.date.slice(0, 7) ?? "");
  const [start, setStart] = useState(initial?.start ?? "");
  const [end, setEnd] = useState(initial?.end ?? "");
  const range: ReportRange = { kind, date: kind === "monthly" ? `${month}-01` : date, start, end };
  let preview = "请选择日期以预览范围。";
  let valid = false;
  try { preview = reportRangeLabel(range); valid = true; } catch { /* 尚未填写完整。 */ }

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = dialog.current;
    node?.showModal();
    return () => { node?.close(); previousFocus?.focus(); };
  }, []);

  return <dialog ref={dialog} className="wb-range-dialog" aria-labelledby="range-title"
    onCancel={event => { event.preventDefault(); onClose(); }}>
    <form onSubmit={event => {
      event.preventDefault();
      if (valid) { resolveReportRange(range); onConfirm(range); }
    }}>
      <div className="wb-dialog-head">
        <div><p className="eyebrow">报告范围</p><h2 id="range-title">选择报告类型与时间</h2></div>
        <button type="button" className="wb-btn wb-btn-sm" aria-label="关闭范围选择" onClick={onClose}><X size={18} /></button>
      </div>
      <p className="wb-hint">先选择报告类型，再确认本次分析覆盖的日期。</p>
      <div className="wb-range-types" role="group" aria-label="报告类型">
        {(["daily", "weekly", "monthly"] as const).map((value, index) =>
          <button type="button" key={value} aria-pressed={kind === value} onClick={() => setKind(value)}>
            <strong>{["日报", "周报", "月报"][index]}</strong>
            <small>{["单个报告日", "连续 7 天", "完整自然月"][index]}</small>
          </button>)}
      </div>
      {kind === "monthly" ? <label className="wb-field"><span>报告月份</span>
        <input autoFocus type="month" value={month} onChange={event => setMonth(event.target.value)} /></label>
        : kind !== "custom" && <label className="wb-field"><span>{kind === "weekly" ? "周报结束日（含当日及之前6日）" : "报告日期"}</span>
          <input autoFocus type="date" value={date} onChange={event => setDate(event.target.value)} /></label>}
      <details className="wb-accordion" open={kind === "custom" || undefined}>
        <summary>更多范围</summary>
        <button className="wb-btn wb-btn-sm" type="button" aria-pressed={kind === "custom"} onClick={() => setKind("custom")}>自定义区间</button>
        {kind === "custom" && <div className="wb-row">
          <label className="wb-field"><span>开始日期</span><input type="date" value={start} onChange={event => setStart(event.target.value)} /></label>
          <label className="wb-field"><span>结束日期</span><input type="date" value={end} onChange={event => setEnd(event.target.value)} /></label>
        </div>}
      </details>
      <div className="wb-range-preview" aria-live="polite">{preview}</div>
      <p className="wb-hint">区间含首尾日，最多366天。缺测保留为缺口，不补造观测。</p>
      <div className="wb-dialog-actions">
        <button type="button" className="wb-btn" onClick={onClose}>取消</button>
        <button className="wb-btn wb-btn-primary" disabled={!valid}>确认范围</button>
      </div>
    </form>
  </dialog>;
}
