"use client";

import { useEffect, useRef, useState } from "react";
import { FileUp, Loader2, X } from "lucide-react";
import type { ReportKind } from "@/contracts/report-period";
import type { EngineeringSetup, EngineeringSetupField } from "@/contracts/project-setup";
import type { ReadReport, StoredFile } from "@/contracts/monitoring-files";
import {
  unconfirmedMonitoringMetrics,
  MonitoringParameters,
  type MonitoringMetric,
} from "./monitoring-parameters";
import { reportRangeLabel, resolveReportRange, type ReportRange } from "./report-range";

export type { EngineeringSetup };

export type GuidedProjectInput = {
  name: string;
  engineering_type: string;
  parameters: Record<string, unknown>;
  range: ReportRange;
};

export type GuidedProjectPreparation = {
  project_id: string;
  file: StoredFile;
  read_report: ReadReport | null;
  detected_metrics: MonitoringMetric[];
  monitoring_definitions: MonitoringMetric[];
  available_dates: string[];
  adapter_version: string;
  engineering_revision: number;
};

export type GuidedRunInput = {
  project: GuidedProjectInput;
  preparation: GuidedProjectPreparation;
  parameters: Record<string, unknown>;
  generate_report: boolean;
  report_mode: "ai" | "template";
};

const STEP_LABELS = ["基本信息", "工程条件", "报告范围", "监测数据", "确认运行"];
const REPORT_TYPES: Array<{ kind: ReportKind; label: string; note: string }> = [
  { kind: "daily", label: "日报", note: "单个报告日" },
  { kind: "weekly", label: "周报", note: "连续 7 天" },
  { kind: "monthly", label: "月报", note: "完整自然月" },
];

function firstReportKind(setup?: EngineeringSetup): ReportKind {
  return (["daily", "weekly", "monthly", "custom"] as const)
    .find(kind => !setup || setup.supported_reports.includes(kind)) ?? "daily";
}

function completeParameters(
  fields: EngineeringSetupField[],
  values: Record<string, unknown>,
): Record<string, unknown> {
  const entries: Array<[string, unknown]> = [];
  for (const field of fields) {
    const value = values[field.key];
    if (field.input_type === "checkbox") {
      entries.push([field.key, value === true]);
      continue;
    }
    if (field.input_type === "number") {
      if (value === "" || value === undefined || value === null) {
        if (!field.required) entries.push([field.key, null]);
      } else {
        entries.push([field.key, Number(value)]);
      }
      continue;
    }
    if (typeof value === "string" && value) entries.push([field.key, value]);
  }
  return Object.fromEntries(entries);
}

function missingRangeDates(range: ReportRange, availableDates: string[]): string[] {
  const resolved = resolveReportRange(range);
  const start = resolved.report_period?.start_date ?? resolved.report_date;
  const end = resolved.report_period?.end_date ?? resolved.report_date;
  const available = new Set(availableDates);
  const missing: string[] = [];
  for (
    let time = Date.parse(`${start}T00:00:00Z`);
    time <= Date.parse(`${end}T00:00:00Z`);
    time += 86_400_000
  ) {
    const date = new Date(time).toISOString().slice(0, 10);
    if (!available.has(date)) missing.push(date);
  }
  return missing;
}

export function NewProjectDialog({
  setups,
  busy,
  error,
  onClose,
  onCreateDetailed,
  onPrepare,
  onRun,
}: {
  setups: EngineeringSetup[];
  busy: boolean;
  error?: string;
  onClose: () => void;
  onCreateDetailed: (input: GuidedProjectInput) => void;
  onPrepare: (
    input: GuidedProjectInput,
    file: File,
  ) => Promise<GuidedProjectPreparation>;
  onRun: (input: GuidedRunInput) => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [engineeringType, setEngineeringType] = useState(setups[0]?.id ?? "");
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  const setup = setups.find(item => item.id === engineeringType) ?? setups[0];
  const [kind, setKind] = useState<ReportKind>(() => firstReportKind(setup));
  const [date, setDate] = useState("");
  const [month, setMonth] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [monitoringFile, setMonitoringFile] = useState<File | null>(null);
  const [preparation, setPreparation] = useState<GuidedProjectPreparation | null>(null);
  const [runtimeParameters, setRuntimeParameters] = useState<Record<string, unknown>>({});
  const [generateReport, setGenerateReport] = useState(false);
  const [reportMode, setReportMode] = useState<"ai" | "template">("template");
  const [workflowError, setWorkflowError] = useState("");
  const [workflowStage, setWorkflowStage] = useState("");

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = dialog.current;
    node?.showModal();
    return () => {
      node?.close();
      previousFocus?.focus();
    };
  }, []);

  const fieldsComplete = Boolean(setup) && setup.core_fields.every(field => {
    const value = parameters[field.key];
    if (!field.required) {
      if (field.input_type !== "number" || value === "" || value === undefined || value === null) return true;
    }
    if (field.input_type === "checkbox") return value === true;
    if (field.input_type === "number") {
      const number = Number(value);
      return Number.isFinite(number) && number > 0 &&
        (field.key !== "excavation_depth_m" || number <= 200);
    }
    return typeof value === "string" && value.trim().length > 0;
  });
  const range: ReportRange = {
    kind,
    date: kind === "monthly" ? `${month}-01` : date,
    start,
    end,
  };
  let rangeResult: { valid: boolean; label: string };
  try {
    rangeResult = {
      valid: Boolean(setup?.supported_reports.includes(kind)),
      label: reportRangeLabel(range),
    };
  } catch {
    rangeResult = { valid: false, label: "尚未选择完整报告范围" };
  }
  const projectInput: GuidedProjectInput | null = setup ? {
    name: name.trim(),
    engineering_type: setup.id,
    parameters: completeParameters(setup.core_fields, parameters),
    range,
  } : null;
  const incompleteMetrics = preparation
    ? unconfirmedMonitoringMetrics(
      preparation.detected_metrics,
      preparation.monitoring_definitions,
      runtimeParameters,
    )
    : [];
  const uncoveredDates = preparation && rangeResult.valid
    ? missingRangeDates(range, preparation.available_dates)
    : [];
  const quickRunReady = Boolean(
    preparation &&
    preparation.read_report?.ok !== false &&
    uncoveredDates.length === 0,
  );

  function moveNext() {
    if (step === 0 && name.trim() && setup) setStep(1);
    else if (step === 1 && fieldsComplete) setStep(2);
    else if (step === 2 && rangeResult.valid) setStep(preparation ? 4 : 3);
  }

  async function prepareQuickRun() {
    if (!projectInput || !monitoringFile || busy) return;
    setWorkflowError("");
    setWorkflowStage("正在创建工程、上传并解析监测文件…");
    try {
      const prepared = await onPrepare(projectInput, monitoringFile);
      setPreparation(prepared);
      setRuntimeParameters(projectInput.parameters);
      if (prepared.read_report?.ok === false) {
        setWorkflowError(
          (prepared.read_report.errors ?? []).join("；") ||
          "监测文件解析失败，请修正后重新选择。",
        );
        return;
      }
      setStep(4);
    } catch (caught) {
      setWorkflowError(caught instanceof Error ? caught.message : "快速链路准备失败。");
    } finally {
      setWorkflowStage("");
    }
  }

  async function runQuickAnalysis() {
    if (!projectInput || !preparation || !quickRunReady || busy) return;
    setWorkflowError("");
    setWorkflowStage("正在保存工程参数并运行分析…");
    try {
      await onRun({
        project: projectInput,
        preparation,
        parameters: runtimeParameters,
        generate_report: generateReport,
        report_mode: reportMode,
      });
    } catch (caught) {
      setWorkflowError(caught instanceof Error ? caught.message : "自动运行失败，可重试或转入详细流程。");
    } finally {
      setWorkflowStage("");
    }
  }

  return <dialog
    ref={dialog}
    className="wb-range-dialog wb-project-dialog"
    aria-labelledby="new-project-title"
    onCancel={event => {
      event.preventDefault();
      if (!busy) onClose();
    }}
  >
    <form onSubmit={event => {
      event.preventDefault();
      if (step < 3) {
        moveNext();
        return;
      }
      if (step === 3) {
        void prepareQuickRun();
        return;
      }
      void runQuickAnalysis();
    }}>
      <div className="wb-dialog-head">
        <div>
          <p className="eyebrow">新建工程</p>
          <h2 id="new-project-title">{STEP_LABELS[step]}</h2>
        </div>
        <button
          type="button"
          className="wb-btn wb-icon-btn"
          aria-label="关闭新建工程"
          title="关闭"
          disabled={busy}
          onClick={onClose}
        >
          <X size={18} aria-hidden="true" />
        </button>
      </div>

      <ol className="wb-dialog-progress" aria-label="新建工程进度">
        {STEP_LABELS.map((label, index) => (
          <li key={label} className={index === step ? "active" : index < step ? "done" : ""}>
            <span>{index + 1}</span>{label}
          </li>
        ))}
      </ol>

      {(workflowError || error) && <div role="alert" className="wb-alert wb-alert-error">
        {workflowError || error}
      </div>}
      {workflowStage && <p role="status" className="wb-hint">
        <Loader2 size={14} className="wb-spin" aria-hidden="true" /> {workflowStage}
      </p>}

      {step === 0 && <div className="wb-dialog-stage">
        <label className="wb-field">
          <span>工程类型</span>
          <select
            autoFocus
            value={engineeringType}
            onChange={event => {
              const nextSetup = setups.find(item => item.id === event.target.value);
              if (!nextSetup) return;
              setEngineeringType(nextSetup.id);
              setParameters({});
              setMonitoringFile(null);
              setPreparation(null);
              setRuntimeParameters({});
              setWorkflowError("");
              if (nextSetup && !nextSetup.supported_reports.includes(kind)) {
                setKind(firstReportKind(nextSetup));
              }
            }}
          >
            {setups.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label className="wb-field">
          <span>工程名称</span>
          <input
            required
            maxLength={100}
            value={name}
            onChange={event => setName(event.target.value)}
            placeholder="例如：杭州一期基坑工程"
          />
        </label>
      </div>}

      {step === 1 && setup && <div className="wb-dialog-stage wb-dialog-fields">
        {setup.core_fields.map((field, index) => (
          <label className="wb-field" key={field.key}>
            <span>{field.label}{field.required ? "（必填）" : "（可留空）"}</span>
            {field.choices ? <select
              autoFocus={index === 0}
              value={String(parameters[field.key] ?? "")}
              onChange={event => setParameters(current => ({
                ...current,
                [field.key]: event.target.value,
              }))}
            >
              <option value="">请选择实际{field.label}</option>
              {field.choices.map(choice => (
                <option key={choice} value={choice}>{field.choice_labels?.[choice] ?? choice}</option>
              ))}
            </select> : field.input_type === "checkbox" ? <input
              autoFocus={index === 0}
              type="checkbox"
              checked={parameters[field.key] === true}
              onChange={event => setParameters(current => ({
                ...current,
                [field.key]: event.target.checked,
              }))}
            /> : <input
              autoFocus={index === 0}
              type={field.input_type ?? "text"}
              min={field.input_type === "number" ? "0" : undefined}
              max={field.key === "excavation_depth_m" ? "200" : undefined}
              step={field.input_type === "number" ? "any" : undefined}
              value={String(parameters[field.key] ?? "")}
              onChange={event => setParameters(current => ({
                ...current,
                [field.key]: event.target.value,
              }))}
            />}
          </label>
        ))}
      </div>}

      {step === 2 && setup && <div className="wb-dialog-stage">
        <div className="wb-range-types" role="group" aria-label="首次报告类型">
          {REPORT_TYPES.map(item => (
            <button
              type="button"
              key={item.kind}
              disabled={!setup.supported_reports.includes(item.kind)}
              aria-pressed={kind === item.kind}
              onClick={() => setKind(item.kind)}
            >
              <strong>{item.label}</strong>
              <small>{item.note}</small>
            </button>
          ))}
        </div>
        {kind === "monthly" ? <label className="wb-field">
          <span>报告月份</span>
          <input autoFocus type="month" value={month} onChange={event => setMonth(event.target.value)} />
        </label> : kind !== "custom" ? <label className="wb-field">
          <span>{kind === "weekly" ? "周报结束日（含当日及之前6日）" : "报告日期"}</span>
          <input autoFocus type="date" value={date} onChange={event => setDate(event.target.value)} />
        </label> : <div className="wb-row">
          <label className="wb-field">
            <span>开始日期</span>
            <input autoFocus type="date" value={start} onChange={event => setStart(event.target.value)} />
          </label>
          <label className="wb-field">
            <span>结束日期</span>
            <input type="date" value={end} onChange={event => setEnd(event.target.value)} />
          </label>
        </div>}
        {setup.supported_reports.includes("custom") && <button
          className="wb-btn wb-btn-sm"
          type="button"
          aria-pressed={kind === "custom"}
          onClick={() => setKind("custom")}
        >
          自定义区间
        </button>}
        <div className="wb-range-preview" aria-live="polite">{rangeResult.label}</div>
        <dl className="wb-project-summary">
          <dt>工程</dt><dd>{name.trim()}</dd>
          <dt>类型</dt><dd>{setup.name}</dd>
        </dl>
      </div>}

      {step === 3 && <div className="wb-dialog-stage">
        <p className="wb-hint">
          选择本次报告的监测文件。系统将创建工程、上传文件并识别测项；
          可选规范和工况资料仍可在详细流程中补充。
        </p>
        <div className="wb-drop wb-dialog-upload">
          <input
            id="wb-guided-monitoring-file"
            type="file"
            aria-label="快速链路监测数据文件"
            accept=".csv,.tsv,.txt,.xlsx,.xlsm"
            disabled={busy}
            onChange={event => {
              setMonitoringFile(event.target.files?.[0] ?? null);
              setPreparation(null);
              setWorkflowError("");
            }}
          />
          <label htmlFor="wb-guided-monitoring-file">
            <FileUp size={15} aria-hidden="true" />
            选择监测数据文件
          </label>
          <p>支持 CSV / TSV / XLSX，单文件上限沿用现有上传规则。</p>
        </div>
        {monitoringFile && <div className="wb-meta">
          <span className="wb-chip">{monitoringFile.name}</span>
          <span className="wb-chip">{(monitoringFile.size / 1024).toFixed(1)} KB</span>
        </div>}
        {preparation?.read_report && <div className={`wb-alert ${
          preparation.read_report.ok === false ? "wb-alert-error" : "wb-alert-ok"
        }`}>
          {preparation.read_report.ok === false
            ? (preparation.read_report.errors ?? []).join("；")
            : `已识别 ${preparation.read_report.data_rows ?? 0} 行监测数据。`}
        </div>}
      </div>}

      {step === 4 && preparation && <div className="wb-dialog-stage">
        <div className="wb-alert wb-alert-info">
          <div>
            <strong>文件已上传，运行前完成最后确认</strong>
            <p>{preparation.file.original_name} · {rangeResult.label}</p>
          </div>
        </div>
        {setup?.id === "tunnel" && <MonitoringParameters
          metrics={preparation.detected_metrics}
          definitions={preparation.monitoring_definitions}
          parameters={runtimeParameters}
          onChange={setRuntimeParameters}
        />}
        {incompleteMetrics.length > 0 && <div className="wb-alert wb-alert-warn">
          <div>以下测项尚未确认控制值：{incompleteMetrics.join("、")}。
            可以继续运行；系统只会在输入语义足够时派生累计量和速率，不会补造语义或阈值，
            无法可靠判定的风险将标为“未知”并进入人工复核。
          </div>
        </div>}
        {uncoveredDates.length > 0 && <div className="wb-alert wb-alert-warn">
          <div>
            上传数据未覆盖报告范围：{uncoveredDates.slice(0, 5).join("、")}
            {uncoveredDates.length > 5 && ` 等 ${uncoveredDates.length} 天`}。请关闭后通过详细流程补充文件，
            或返回报告范围重新选择。
          </div>
        </div>}
        <label className="wb-report-toggle">
          <input
            type="checkbox"
            checked={generateReport}
            onChange={event => setGenerateReport(event.target.checked)}
          />
          同时生成并审计监测报告三件套
        </label>
        {generateReport && <label className="wb-field">
          <span>报告生成方式</span>
          <select
            value={reportMode}
            onChange={event => setReportMode(event.target.value as "ai" | "template")}
          >
            <option value="template">仅模板：计算结果与附表</option>
            <option value="ai">AI分析与独立审查</option>
          </select>
        </label>}
        <dl className="wb-project-summary">
          <dt>工程</dt><dd>{name.trim()}</dd>
          <dt>类型</dt><dd>{setup?.name}</dd>
          <dt>范围</dt><dd>{rangeResult.label}</dd>
          <dt>文件</dt><dd>{preparation.file.original_name}</dd>
          <dt>运行方式</dt><dd>{generateReport
            ? reportMode === "ai" ? "AI分析与独立审查" : "模板报告与文件审计"
            : "仅确定性计算"}</dd>
        </dl>
      </div>}

      <div className="wb-dialog-actions">
        {step === 0 ? <button type="button" className="wb-btn" disabled={busy} onClick={onClose}>取消</button>
          : <button
            type="button"
            className="wb-btn"
            disabled={busy || Boolean(preparation && step === 2)}
            onClick={() => setStep(current => current === 4 && preparation ? 2 : current - 1)}
          >
            上一步
          </button>}
        {step === 4 && preparation && <button
          type="button"
          className="wb-btn"
          disabled={busy}
          onClick={() => {
            setPreparation(null);
            setRuntimeParameters({});
            setStep(3);
          }}
        >
          更换监测文件
        </button>}
        {step === 2 && !preparation && <button
          type="button"
          className="wb-btn"
          disabled={busy || !rangeResult.valid || !projectInput}
          onClick={() => {
            if (projectInput) onCreateDetailed(projectInput);
          }}
        >
          创建后进入详细流程
        </button>}
        {step < 3 ? <button
          className="wb-btn wb-btn-primary"
          disabled={busy || (
            step === 0
              ? !name.trim() || !setup
              : step === 1
                ? !fieldsComplete
                : !rangeResult.valid
          )}
        >
          下一步
        </button> : step === 3 ? <button
          className="wb-btn wb-btn-primary"
          disabled={busy || !monitoringFile || !projectInput}
        >
          {busy ? "正在准备…" : "创建工程并识别文件"}
        </button> : <button
          className="wb-btn wb-btn-primary"
          disabled={busy || !quickRunReady}
        >
          {busy ? "正在运行…" : "运行分析并查看结果"}
        </button>}
      </div>
    </form>
  </dialog>;
}
