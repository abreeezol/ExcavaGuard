import type { PersistedRun } from "@/contracts/runs";
import { reportRangeLabel } from "./report-range";

const CONDITION_LABELS: Record<string, string> = {
  pipeline_type: "管线类型", road_type: "道路类型", design_values: "设计值", danger_signals: "险情信号",
};

export function RunConditions({ record, currentName }: { record: PersistedRun; currentName?: string }) {
  const input = record.request;
  const context = input.context;
  const range = reportRangeLabel({
    kind: input.report_period?.type ?? "daily", date: input.report_date,
    start: input.report_period?.start_date ?? input.report_date,
    end: input.report_period?.end_date ?? input.report_date,
  });
  return <section className="wb-card" aria-label="本次工程条件">
    <h2>本次工程条件</h2>
    <p className="wb-hint">当前报告保存的条件快照</p>
    <dl className="wb-condition-list">
      <dt>工程名称</dt><dd>{input.project?.name ?? "未提供"}</dd>
      <dt>报告范围</dt><dd>{range}</dd>
      <dt>安全等级</dt><dd>{context.safety_level ?? "未提供"}</dd>
      <dt>设计深度 H</dt><dd>{context.excavation_depth_m != null ? `${context.excavation_depth_m} m` : "未提供"}</dd>
    </dl>
    <details className="wb-accordion"><summary>完整工程条件</summary>
      <dl className="wb-condition-list">
        <dt>工程 ID</dt><dd>{input.project_id ?? "未提供"}</dd>
        <dt>底板浇筑日期</dt><dd>{context.post_slab_from ?? "未提供"}</dd>
        <dt>判据适用条件</dt><dd>{context.support_type ?? "未提供"}</dd>
        {Object.entries(context).filter(([key]) =>
          !["safety_level", "support_type", "excavation_depth_m", "post_slab_from"].includes(key),
        ).map(([key, value]) => <div className="wb-condition-extra" key={key}>
          <dt>{CONDITION_LABELS[key] ?? key}</dt>
          <dd>{value == null ? "未提供" : typeof value === "object" ? JSON.stringify(value) : String(value)}</dd>
        </div>)}
      </dl>
      {currentName && currentName !== input.project?.name && <p className="wb-hint">工程当前名称：{currentName}</p>}
    </details>
  </section>;
}
