import type { PersistedRun } from "@/contracts/runs";
import { reportRangeLabel } from "./report-range";

const CONDITION_LABELS: Record<string, string> = {
  pipeline_type: "管线类型", road_type: "道路类型", design_values: "设计值", danger_signals: "险情信号",
};

type ConditionField = { key: string; label: string; choice_labels?: Record<string, string> };

function conditionValue(value: unknown, field?: ConditionField): string {
  if (value == null) return "未提供";
  if (field?.key === "excavation_depth_m") return `${value} m`;
  if (typeof value === "object") return JSON.stringify(value);
  return field?.choice_labels?.[String(value)] ?? String(value);
}

export function RunConditions({ record, currentName, fields = [] }: {
  record: PersistedRun; currentName?: string; fields?: ConditionField[];
}) {
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
      {fields.map(field => <div className="wb-condition-extra" key={field.key}>
        <dt>{field.label}</dt><dd>{conditionValue(context[field.key], field)}</dd>
      </div>)}
    </dl>
    <details className="wb-accordion"><summary>完整工程条件</summary>
      <dl className="wb-condition-list">
        <dt>工程 ID</dt><dd>{input.project_id ?? "未提供"}</dd>
        {Object.entries(context).map(([key, value]) => <div className="wb-condition-extra" key={key}>
          <dt>{fields.find(field => field.key === key)?.label ?? CONDITION_LABELS[key] ?? key}</dt>
          <dd>{conditionValue(value, fields.find(field => field.key === key))}</dd>
        </div>)}
      </dl>
      {currentName && currentName !== input.project?.name && <p className="wb-hint">工程当前名称：{currentName}</p>}
    </details>
  </section>;
}
