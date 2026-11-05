"use client";
import { MonitoringParameters,type MonitoringMetric } from "./monitoring-parameters";
import { ProfessionalReviewPanel } from "./professional-review-panel";
import { ProjectContextPanel } from "./project-context-panel";
import { ProjectStandards } from "./project-standards";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileUp,
  Loader2,
  Play,
  ShieldAlert,
  Trash2,
  Upload,
} from "lucide-react";
import { presetReportPeriod, reportPeriodSchema, type ReportKind } from "@/contracts/report-period";
import { listFilesResponseSchema, type ReadReport, type StoredFile, type StrictnessReport } from "@/contracts/monitoring-files";
import type { AccessStatus } from "@/contracts/access";
import type { CreateRunRequest, PersistedRun, ReviewRequest, RunSummary } from "@/contracts/runs";
import { persistedRunSchema, runListResponseSchema } from "@/contracts/runs";
import type { EngineerRiskEvaluationInput } from "@/contracts/engineer-evaluation";
import { decisionLabel, executionLabel, RunDelivery } from "./run-delivery";

/**
 * 可视化测试工作台（客户端）
 *
 * 走的是真实链路：上传 → `/api/monitoring-files`；上传规范 → `/api/standards`；
 * 运行分析 → `/api/runs`（内部以子进程调用确定性计算引擎）。
 * 页面本身不做任何判定，只展示引擎返回的结构化载荷。
 */

// --- 类型（与后端载荷对应，只声明用得到的字段） ---------------------------

type Level = "正常" | "关注" | "预警" | "报警" | "危险报警" | "未知";

type PayloadItem = {
  point_id?: string;
  point_name?: string | null;
  metric_key?: string;
  metric_name?: string;
  timestamp?: string;
  baseline?: number | null;
  previous?: number | null;
  current?: number | null;
  interval_days?: number | null;
  cumulative?: number | null;
  single_change?: number | null;
  rate?: number | null;
  slope?: number | null;
  problem_category?: string;
  risk_level?: Level;
  utilization?: number | null;
  checks?: Array<Record<string, unknown>>;
  effective_standard?: {
    origin?: string;
    origin_display?: string;
    rule_id?: string | null;
    source_label?: string | null;
    overridden_fields?: string[];
    looser_details?: Array<Record<string, unknown>>;
  };
  rule_id?: string | null;
  evidence?: { standard?: string; clause?: string; note?: string };
  abstain?: string[];
  abstain_reasons?: string[];
  flags?: string[];
  needs_review?: boolean;
};

type Payload = {
  schema?: string;
  period?: {
    label: string; start_date: string; end_date: string; calendar_days: number; observed_days: number;
    channel_count: number; observation_count: number; warning_point_days: number; unknown_observation_count: number;
    missing_dates: string[];
    recurring_warnings: Array<{ point_id: string; metric_name: string; warning_days: number; max_consecutive_warning_days: number }>;
    daily_summaries: Array<{ date: string; observation_count: number; warning_count: number; unknown_count: number; worst_known_risk: string; missing: boolean }>;
  };
  context?: Record<string, unknown>;
  standards_sources?: Array<Record<string, unknown>>;
  data_quality?: { issue_count?: number; by_code?: Record<string, number>; blocked_records?: number };
  summary?: {
    total?: number;
    by_risk_level?: Record<string, number>;
    by_problem_category?: Record<string, number>;
    by_data_origin?: Record<string, number>;
    abstain?: Record<string, number>;
    overall_risk_level?: Level;
  };
  alerts?: PayloadItem[];
  review_queue?: PayloadItem[];
  standard_override_warnings?: Array<{
    metric_key?: string;
    metric_name?: string;
    differences?: Array<{
      field_display?: string;
      user_value?: number | null;
      default_value?: number | null;
      unit?: string;
      delta_pct?: number;
      severity?: string;
      default_basis?: string;
      default_evidence?: { standard?: string; clause?: string };
    }>;
  }>;
  items?: PayloadItem[];
  disclaimer?: string;
  note?: string;
};

type RunResponse = {
  record: PersistedRun;
  run_id?: string;
  created_at?: string;
  monitoring_file_id?: string;
  standards_file_id?: string | null;
  effective_standard_origin?: string | null;
  engine?: { elapsed_ms?: number; python?: string; records?: number };
  read_report?: ReadReport | null;
  summary?: {
    records?: number;
    real_records?: number;
    simulated_records?: number;
    data_quality_issues?: number;
    data_quality_blocked?: number;
    judgments?: number;
    effective_standard_origin?: string;
    overall_risk_level?: Level;
    by_risk_level?: Record<string, number>;
    abstain?: Record<string, number>;
  };
  payload?: Payload;
};

type ApiErrorBody = { error?: { code?: string; message?: string; fields?: string[] } };

// --- 展示辅助 -------------------------------------------------------------

const LEVEL_KEY: Record<string, string> = {
  正常: "normal",
  关注: "watch",
  预警: "warning",
  报警: "alarm",
  危险报警: "danger",
  未知: "unknown",
};

const LEVEL_ORDER: Level[] = ["危险报警", "报警", "预警", "关注", "正常", "未知"];

function LevelBadge({ level }: { level?: string | null }) {
  const value = level ?? "未知";
  return <span className={`wb-level wb-level-${LEVEL_KEY[value] ?? "unknown"}`}>{value}</span>;
}

function num(value: unknown, digits = 2): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="wb-field">
      <span>{label}</span>
      {children}
    </label>
  );
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as ApiErrorBody;
    const code = body.error?.code ? `[${body.error.code}] ` : "";
    const fields = body.error?.fields?.length ? `（字段：${body.error.fields.join("、")}）` : "";
    return `${code}${body.error?.message ?? "请求失败"}${fields}`;
  } catch {
    return `请求失败（HTTP ${response.status}）`;
  }
}

// --- 主组件 ---------------------------------------------------------------

export function ProjectWorkbench({ session, onBusyChange }: {
  session: AccessStatus & { project_id: string }; onBusyChange: (busy: boolean) => void;
}) {
  const project = session.projects?.find(p => p.id === session.project_id);
  const canWrite = project?.role !== "viewer";
  const canReview = !project || ["admin", "reviewer"].includes(project.role);
  const canDelete = !project || project.role === "admin";
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [standardFiles, setStandardFiles] = useState<StoredFile[]>([]);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [historyDate, setHistoryDate] = useState("");
  const [onlyPending, setOnlyPending] = useState(false);
  const [remoteRevision, setRemoteRevision] = useState<number | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncedAt, setSyncedAt] = useState<string | null>(null);
  const [additionalFileIds, setAdditionalFileIds] = useState<string[]>([]);
  const [generateReport, setGenerateReport] = useState(true);
  const [reportMode, setReportMode] = useState<"ai" | "template">("ai");
  const [selectedStandardId, setSelectedStandardId] = useState<string | null>(null);
  const [rerunInput, setRerunInput] = useState<CreateRunRequest | null>(null);
  const [parentRunId, setParentRunId] = useState<string | null>(null);
  const operation = useRef(false);
  const [scene, setScene] = useState<{ engineering_type?:{id:string;name:string}; monitoring_metrics?:MonitoringMetric[]; adapter: { id: string; name: string; version: string; supported_reports: string[]; core_fields: Array<{ key: string; label: string; required: boolean; choices?: string[]; choice_labels?:Record<string,string>; input_type?: string }> }; parameters: Record<string, unknown> | null; revision: number } | null>(null);
  const [detectedMetrics,setDetectedMetrics]=useState<MonitoringMetric[]>([]);
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  function updateCoreParameter(key:string,value:unknown){setParameters(current=>{const next={...current,[key]:value};if(key==='construction_method'){const context={...(current.case_context as Record<string,unknown>??{})};delete context.method;next.case_context=context;}return next;});}
  const [projectName, setProjectName] = useState(project?.name || "工程");
  const [reportDate, setReportDate] = useState("");
  const [windows, setWindows] = useState<Array<{id:string;type:ReportKind;start_date:string;end_date:string;label:string;missing_days:string[]}>>([]);
  const [windowId,setWindowId]=useState("");
  const [windowMessage,setWindowMessage]=useState("");
  const [reportKind, setReportKind] = useState<ReportKind>("daily");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");

  const [monitoring, setMonitoring] = useState<{ file: StoredFile; read_report: ReadReport | null } | null>(null);
  const [standard, setStandard] = useState<{
    file: StoredFile;
    strictness: StrictnessReport;
    report: string;
  } | null>(null);
  const [standardText, setStandardText] = useState("");

  const [result, setResult] = useState<RunResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const apiFetch = useCallback((url: string, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    headers.set("X-Excavaguard-Project", session.project_id);
    return fetch(url, { ...init, headers, cache: "no-store" });
  }, [session.project_id]);
  useEffect(() => {
    let cancelled = false;
    void apiFetch("/api/projects/current/engineering").then(async response => {
      if (!response.ok) throw new Error(await readError(response));
      return response.json();
    }).then(body => { if (!cancelled) { setScene(body); setParameters(body.parameters ?? {}); } }).catch(caught => { if (!cancelled) setError(caught.message); });
    return () => { cancelled = true; };
  }, [apiFetch]);
  useEffect(() => {
    if(!monitoring)return;
    let cancelled=false;
    const timer=setTimeout(()=>{void apiFetch("/api/report-windows",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({file_ids:[monitoring.file.file_id,...additionalFileIds]})}).then(async response=>{const body=await response.json();if(!response.ok)throw new Error(body.error?.message??"周期识别失败");return body;}).then(body=>{
      if(cancelled)return;setWindows(body.windows);setDetectedMetrics(body.detected_metrics??[]);setWindowMessage(body.notice);const first=body.windows[0];if(first&&!parentRunId){setWindowId(first.id);setReportKind(first.type);setReportDate(first.end_date);setPeriodStart(first.start_date);setPeriodEnd(first.end_date);}
    }).catch(error=>{if(!cancelled){setWindows([]);setWindowMessage(error.message);}});},200);
    return()=>{cancelled=true;clearTimeout(timer);};
  },[apiFetch,monitoring,additionalFileIds,parentRunId]);
  useEffect(() => { onBusyChange(busy !== null); }, [busy, onBusyChange]);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const responses = await Promise.all([apiFetch("/api/runs"), apiFetch("/api/monitoring-files"), apiFetch("/api/standards")]);
        for (const response of responses) if (!response.ok) throw new Error(await readError(response));
        const [runs, monitoringFiles, standards] = await Promise.all(responses.map(response => response.json()));
        if (!cancelled) {
          setHistory(runListResponseSchema.parse(runs).runs);
          setFiles(listFilesResponseSchema.parse(monitoringFiles).files);
          setStandardFiles(listFilesResponseSchema.parse(standards).files);
        }
      } catch (caught) { if (!cancelled) setError(caught instanceof Error ? caught.message : "加载项目失败。"); }
    })();
    return () => { cancelled = true; };
  }, [apiFetch]);
  useEffect(() => {
    let cancelled = false;
    let refreshing = false;
    async function sync() {
      if (cancelled || refreshing || operation.current || document.visibilityState === "hidden") return;
      refreshing = true;
      try {
        const responses = await Promise.all([
          apiFetch("/api/runs"), apiFetch("/api/monitoring-files"),
        ]);
        for (const response of responses) if (!response.ok) throw new Error(await readError(response));
        const [runs, uploads] = await Promise.all(responses.map(response => response.json()));
        if (cancelled || operation.current) return;
        const summaries = runListResponseSchema.parse(runs).runs;
        setHistory(summaries);
        setFiles(listFilesResponseSchema.parse(uploads).files);
        const latest = summaries.find(item => item.run_id === result?.record.run_id);
        setRemoteRevision(latest && latest.revision > (result?.record.revision ?? 0) ? latest.revision : null);
        setSyncError(null);
        setSyncedAt(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
      } catch (caught) {
        if (!cancelled) setSyncError(caught instanceof Error ? caught.message : "协作数据同步失败。");
      } finally {
        refreshing = false;
      }
    }
    const timer = window.setInterval(() => void sync(), 15_000);
    const onVisible = () => void sync();
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [apiFetch, result?.record.run_id, result?.record.revision]);

  async function refreshHistory() {
    const response = await apiFetch("/api/runs");
    if (!response.ok) throw new Error(await readError(response));
    const summaries = runListResponseSchema.parse(await response.json()).runs;
    setHistory(summaries);
    const latest = summaries.find(item => item.run_id === result?.record.run_id);
    setRemoteRevision(latest && latest.revision > (result?.record.revision ?? 0) ? latest.revision : null);
    setSyncError(null);
    return summaries;
  }

  async function refreshSharedData() {
    const response = await apiFetch("/api/monitoring-files");
    if (!response.ok) throw new Error(await readError(response));
    const files = listFilesResponseSchema.parse(await response.json()).files;
    await refreshHistory();
    setFiles(files);
    setSyncedAt(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
  }

  function begin(name: string): boolean {
    if (operation.current) return false;
    operation.current = true;
    reset();
    setBusy(name);
    return true;
  }

  function finish() {
    operation.current = false;
    setBusy(null);
  }

  async function perform(name: string, work: () => Promise<void>) {
    if (!begin(name)) return;
    try {
      await work();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "操作失败。");
    } finally {
      finish();
    }
  }

  async function openRun(runId: string) {
    const response = await apiFetch(`/api/runs/${runId}`);
    if (!response.ok) {
      if (response.status === 404 && result?.record.run_id === runId) setResult(null);
      throw new Error(await readError(response));
    }
    const body = await response.json() as RunResponse;
    persistedRunSchema.parse(body.record);
    setResult(body);
    setRemoteRevision(null);
  }

  async function deleteHistory(run: RunSummary) {
    const response = await apiFetch(
      `/api/runs/${run.run_id}?expected_revision=${run.revision}`,
      { method: "DELETE" },
    );
    if (!response.ok) {
      if (response.status === 409) await refreshHistory();
      throw new Error(await readError(response));
    }
    const deleted = await response.json() as { deleted?: unknown; cleanup_complete?: unknown };
    if (deleted.deleted !== true || typeof deleted.cleanup_complete !== "boolean") {
      throw new Error("删除响应不完整，请刷新历史确认结果。");
    }
    setHistory((current) => current.filter((item) => item.run_id !== run.run_id));
    if (result?.record.run_id === run.run_id) setResult(null);
    if (parentRunId === run.run_id) {
      setParentRunId(null);
      setRerunInput(null);
    }
    await refreshHistory();
    setNotice(deleted.cleanup_complete
      ? `已删除运行 ${run.run_id.slice(0, 8)} 及关联报告产物。`
      : `已删除运行 ${run.run_id.slice(0, 8)}；部分云端报告对象需管理员继续清理。`);
  }

  async function loadInputs() {
    const record = result?.record;
    if (!record) return;
    const response = await apiFetch("/api/monitoring-files");
    if (!response.ok) throw new Error(await readError(response));
    const files = (await response.json() as { files: StoredFile[] }).files;
    const file = files.find((file) => file.file_id === record.request.monitoring_file_id);
    if (!file) throw new Error("原监测文件已不可用，请重新上传。");
    const input = record.request;
    const additional = record.request.additional_monitoring_file_ids ?? [];
    if (additional.some(id => !files.some(file => file.file_id === id))) {
      throw new Error("参与汇总的监测文件已不可用，请重新上传。");
    }
    setMonitoring({ file, read_report: (record.result?.read_report as ReadReport | null) ?? null });
    setFiles(files);
    setAdditionalFileIds(additional);
    if (!scene?.parameters) setParameters(input.context);
    setProjectName(project?.name ?? input.project?.name ?? "");
    setReportDate(input.report_date);
    setReportKind(input.report_period?.type ?? "daily");
    setPeriodStart(input.report_period?.start_date ?? input.report_date);
    setPeriodEnd(input.report_period?.end_date ?? input.report_date);
    const revising = record.review?.decision === "needs_changes" || (!record.review && Boolean(record.revision_feedback));
    setGenerateReport(revising || (input.options?.generate_report ?? true));
    setReportMode(revising ? "ai" : (input.options?.report_mode ?? "ai"));
    setSelectedStandardId(input.standards_file_id ?? null);
    setStandard(null);
    setStandardText("");
    setRerunInput(input);
    setParentRunId(record.run_id);
    setNotice(revising ? "已载入原输入并开启AI报告；运行后将逐项回应退回意见，未解决事项交由人工确认。"
      : `已加载 ${record.run_id.slice(0, 8)} 的输入；修正后点“运行分析”将创建关联运行。`);
  }

  async function review(
    decision: ReviewRequest["decision"],
    reason: string,
    evaluations: EngineerRiskEvaluationInput[],
  ) {
    const record = result?.record;
    const draft = record?.result?.agent_run?.state.report_draft;
    if (!record || !draft) return;
    const response = await apiFetch(`/api/runs/${record.run_id}/review`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_revision: record.revision,
        draft_ref: draft.ref,
        decision,
        reason,
        evaluations,
      }),
    });
    if (!response.ok) {
      const message = await readError(response);
      if (response.status === 409) {
        await refreshHistory();
      }
      throw new Error(message);
    }
    const body = await response.json() as RunResponse;
    persistedRunSchema.parse(body.record);
    setResult(body);
    await refreshHistory();
    setRemoteRevision(null);
  }

  async function saveEvaluations(evaluations: EngineerRiskEvaluationInput[], reason: string) {
    const record = result?.record;
    const draft = record?.result?.agent_run?.state.report_draft;
    if (!record || !draft) return;
    const response = await apiFetch(`/api/runs/${record.run_id}/evaluations`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: record.revision, draft_ref: draft.ref, evaluations, reason }),
    });
    if (!response.ok) {
      const message = await readError(response);
      if (response.status === 409) {
        await refreshHistory();
      }
      throw new Error(message);
    }
    const body = await response.json() as RunResponse;
    persistedRunSchema.parse(body.record);
    setResult(body);
    await refreshHistory();
    setRemoteRevision(null);
    setNotice("风险评价已暂存到当前工程，其他成员可加载最新运行查看和继续复核。");
  }

  async function download(url: string, fileName: string) {
    const response = await apiFetch(url);
    if (!response.ok) throw new Error(await readError(response));
    const blobUrl = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = blobUrl;
    anchor.download = fileName;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
  }

  function reset() {
    setError(null);
    setNotice(null);
  }

  async function uploadMonitoring(file: File) {
    if (!begin("upload")) return;
    setResult(null);
    try {
      const form = new FormData();
      form.set("file", file);
      const response = await apiFetch("/api/monitoring-files", { method: "POST", body: form });
      if (!response.ok) {
        setError(await readError(response));
        return;
      }
      const body = (await response.json()) as { file: StoredFile; read_report: ReadReport | null };
      setMonitoring({ file: body.file, read_report: body.read_report });
      setAdditionalFileIds([]);
      setFiles(old => [body.file, ...old.filter(f => f.file_id !== body.file.file_id)]);
      if (body.read_report?.ok === false) {
        setNotice("文件已保存，但缺少必填列，运行分析会被拒绝。请对照下方提示修改后重新上传。");
      }
    } catch (caught) {
      setError(`上传失败：${caught instanceof Error ? caught.message : String(caught)}`);
    } finally {
      finish();
    }
  }

  async function uploadStandard() {
    if (operation.current) return;
    reset();
    const text = standardText.trim();
    if (!text) {
      setError("请先粘贴或选择用户规范 JSON。");
      return;
    }
    let payload: unknown;
    try {
      payload = JSON.parse(text);
    } catch (caught) {
      setError(`不是有效 JSON：${caught instanceof Error ? caught.message : String(caught)}`);
      return;
    }
    if (!begin("standard")) return;
    try {
      const response = await apiFetch("/api/standards", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          payload,
          context: parameters,
        }),
      });
      if (!response.ok) {
        setError(await readError(response));
        return;
      }
      const body = (await response.json()) as {
        file: StoredFile;
        strictness: StrictnessReport;
        report: string;
      };
      setStandard(body);
      setStandardFiles(old => [body.file, ...old.filter(f => f.file_id !== body.file.file_id)]);
      setSelectedStandardId(body.file.file_id);
      setNotice(
        body.strictness.has_looser
          ? "用户规范已上传，但存在比默认规范更宽松的阈值，请先阅读下方差异。"
          : "用户规范已上传，未发现比默认规范更宽松的阈值。",
      );
    } catch (caught) {
      setError(`上传规范失败：${caught instanceof Error ? caught.message : String(caught)}`);
    } finally {
      finish();
    }
  }

  async function runAnalysis() {
    if (operation.current) return;
    reset();
    if (!monitoring) {
      setError("请先上传监测数据文件。");
      return;
    }
    if(!reportDate){setError("请先上传数据并选择推荐周期，或展开手动设置填写日期。");return;}
    let reportPeriod;
    try {
      reportPeriod = reportKind === "daily" ? undefined : reportKind === "custom"
        ? reportPeriodSchema.parse({ type: "custom", start_date: periodStart, end_date: periodEnd })
        : presetReportPeriod(reportKind, reportDate);
    } catch {
      setError("请检查报告起止日期：起始日不得晚于结束日，区间最多366天。");
      return;
    }
    if (!begin("run")) return;
    try {
      const response = await apiFetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: session?.project_id,
          parent_run_id: parentRunId ?? undefined,
          monitoring_file_id: monitoring.file.file_id,
          additional_monitoring_file_ids: additionalFileIds,
          standards_file_id: selectedStandardId,
          report_date: reportPeriod?.end_date ?? reportDate,
          report_period: reportPeriod,
          context: parameters,
          project: projectName.trim() ? { ...rerunInput?.project, name: projectName.trim() } : undefined,
          options: { ...rerunInput?.options, generate_report: generateReport, report_mode: reportMode },
        }),
      });
      if (!response.ok) {
        setError(await readError(response));
        return;
      }
      setResult((await response.json()) as RunResponse);
      setRerunInput(null);
      setParentRunId(null);
    } catch (caught) {
      setError(`分析失败：${caught instanceof Error ? caught.message : String(caught)}`);
    } finally {
      // 包括失败运行也进入历史，便于读取已保存的检查点。
      try { await refreshHistory(); } catch { /* 主错误保留在页面。 */ }
      finish();
    }
  }

  const payload = result?.payload;
  const byLevel = payload?.summary?.by_risk_level ?? {};
  const maxLevelCount = Math.max(1, ...Object.values(byLevel));
  const visibleHistory = history.filter(run =>
    (!historyDate || run.report_date === historyDate) &&
    (!onlyPending || (!run.error && !run.decision && run.agent_status === "awaiting_human_review" && run.execution_status === "completed")),
  );

  return (
    <>
      <div className="wb-steps">
        <span className={monitoring ? "done" : ""}>① 工程条件</span>
        <span className={monitoring ? "done" : ""}>② 上传监测数据</span>
        <span className={standard ? "done" : ""}>③ 用户规范（可选）</span>
        <span className={result ? "done" : ""}>④ 运行分析</span>
      </div>

      {error && (
        <div className="wb-alert wb-alert-error" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <div>{error}</div>
        </div>
      )}
      {notice && !error && (
        <div className="wb-alert wb-alert-warn" role="status">
          <AlertTriangle size={16} aria-hidden="true" />
          <div>{notice}</div>
        </div>
      )}

      <div className="wb-grid">
        {/* ---------------- 左列：输入 ---------------- */}
        <div className="wb-col">
          <section className="wb-card" aria-label="运行历史">
            <div className="wb-card-head"><h2>工程共享日报与运行历史</h2></div>
            <div className="wb-actions">
              <button className="wb-btn wb-btn-sm" disabled={busy !== null} onClick={() => void perform("history", refreshSharedData)}>刷新历史</button>
              {result && <button className="wb-btn wb-btn-sm" disabled={busy !== null}
                onClick={() => {
                  if (window.confirm("刷新当前运行会替换未保存的评价和总评，确认继续？")) {
                    void perform("history", () => openRun(result.record.run_id));
                  }
                }}>刷新当前运行</button>}
            </div>
            <p className="wb-hint">本工程最近 100 次运行。每15秒同步成员上传和复核状态；打开同一运行即可协作。{syncedAt && `最近同步 ${syncedAt}。`}</p>
            {syncError && <p role="status" className="wb-hint">自动同步失败：{syncError} 可点击刷新历史重试。</p>}
            <div className="wb-row">
              <Field label="按报告日期筛选"><input type="date" value={historyDate} onChange={event => setHistoryDate(event.target.value)} /></Field>
              <label className="wb-checkbox"><input type="checkbox" checked={onlyPending} onChange={event => setOnlyPending(event.target.checked)} />只看待工程师复核</label>
            </div>
            {remoteRevision && result && <div className="wb-alert wb-alert-warn" role="status"><div>
              该运行已有更新，当前页面仍保留你的未保存内容。
              <button className="wb-btn wb-btn-sm" disabled={busy !== null}
                onClick={() => {
                  if (window.confirm("加载最新运行将替换当前未保存的评价和总评，确认继续？")) {
                    void perform("history", () => openRun(result.record.run_id));
                  }
                }}>加载最新协作版本</button>
            </div></div>}
            <div className="wb-history">
              {visibleHistory.map((run) => (
                <div className="wb-history-row" key={run.run_id}>
                  <button className="wb-history-item"
                    disabled={busy !== null} onClick={() => void perform("history", () => openRun(run.run_id))}>
                    <strong>{run.project_name} · {run.report_period ? `${run.report_period.start_date} 至 ${run.report_period.end_date}` : run.report_date}</strong>
                    <span>{run.run_id.slice(0, 8)} · {run.decision ? decisionLabel(run.decision) : executionLabel(run.execution_status === "completed" && !run.error ? run.agent_status ?? run.execution_status : run.execution_status)}</span>
                    <span>生成者：{run.created_by?.name ?? "历史记录未保存姓名"} · {run.reviewed_by ? `复核人：${run.reviewed_by.name}` : `暂存评价 ${run.evaluation_count ?? 0}${run.risk_evaluation_total != null ? `/${run.risk_evaluation_total}` : ""} 条`}</span>
                  </button>
                  {canDelete && (
                    <button
                      type="button"
                      className="wb-btn wb-history-delete"
                      aria-label={`删除运行 ${run.run_id.slice(0, 8)}`}
                      title={run.execution_status === "running"
                        ? "运行结束后才能删除"
                        : "删除该条运行历史"}
                      disabled={busy !== null || run.execution_status === "running"}
                      onClick={() => {
                        const period = run.report_period
                          ? `${run.report_period.start_date} 至 ${run.report_period.end_date}`
                          : run.report_date;
                        if (!window.confirm(
                          `确认删除“${run.project_name} · ${period}”的运行历史及关联报告产物？此操作不可撤销。`,
                        )) return;
                        void perform("delete", () => deleteHistory(run));
                      }}
                    >
                      <Trash2 size={15} aria-hidden="true" />
                    </button>
                  )}
                </div>
              ))}
              {visibleHistory.length === 0 && <p className="wb-hint">暂无符合筛选条件的运行记录。</p>}
            </div>
          </section>
          <fieldset className="wb-inputs" disabled={busy !== null || !canWrite}>
          <ProjectContextPanel apiFetch={apiFetch} start={() => begin("context")} finish={finish} />
          <ProfessionalReviewPanel apiFetch={apiFetch} canReview={canReview} />
          <section className="wb-card">
            <div className="wb-card-head">
              <span className="wb-step">1</span>
              <h2>工程条件</h2>
              <label>按数据选择报告周期<select value={windowId} onChange={event=>{const selected=windows.find(w=>w.id===event.target.value);if(selected){setWindowId(selected.id);setReportKind(selected.type);setReportDate(selected.end_date);setPeriodStart(selected.start_date);setPeriodEnd(selected.end_date);}}}><option value="">上传数据后自动推荐</option>{windows.map(w=><option key={w.id} value={w.id}>{w.label}{w.missing_days.length?` · 缺${w.missing_days.length}日`:""}</option>)}</select></label>
              <p className="wb-hint">{windowMessage}</p>
            </div>
            <p className="wb-hint">{scene?.engineering_type?.name ?? "正在加载工程条件…"}。请确认核心参数；保存后日常报告自动复用，变更需重新确认。</p>
            <div className="wb-row">
              {scene?.adapter.core_fields.map(field => <Field key={field.key} label={`${field.label}${field.required ? "（必填）" : "（可留空）"}`}>
                {field.choices ? <select value={String(parameters[field.key] ?? "")} onChange={event => updateCoreParameter(field.key,event.target.value)}>
                  <option value="">请选择</option>{field.choices.map(choice => <option key={choice} value={choice}>{field.choice_labels?.[choice]??choice}</option>)}
                </select> : field.input_type === "checkbox" ? <input type="checkbox" checked={parameters[field.key]===true} onChange={event=>updateCoreParameter(field.key,event.target.checked)} /> : <input type={field.input_type ?? "text"} value={String(parameters[field.key] ?? "")} onChange={event => updateCoreParameter(field.key,field.input_type === "number" ? (event.target.value === "" ? null : Number(event.target.value)) : event.target.value)} />}
              </Field>)}
            </div>
            {scene?.engineering_type?.id==='tunnel'&&<MonitoringParameters metrics={monitoring?detectedMetrics:[]} definitions={scene.monitoring_metrics??[]} parameters={parameters} onChange={setParameters}/>}
            {(project?.role === "admin") && <button className="wb-btn wb-btn-sm" type="button" disabled={!scene || busy !== null} onClick={() => {
              if (!scene || !begin("configuration")) return;
              void (async () => { try {
                const response = await apiFetch("/api/projects/current/engineering", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: scene.revision, adapter_version: scene.adapter.version, parameters }) });
                if (!response.ok) throw new Error(await readError(response));
                const body = await response.json(); setScene(current => current ? { ...current, parameters: body.engineering.parameters, revision: body.engineering.revision } : current); setNotice("工程配置已确认保存，后续报告自动复用。");
              } catch (caught) { setError(caught instanceof Error ? caught.message : "配置保存失败。"); } finally { finish(); } })();
            }}>确认并保存工程配置</button>}
            <div className="wb-row">
              <Field label="工程名称（由当前工程确定）">
                <input value={projectName} readOnly />
              </Field>
            </div>
            <details><summary>手动调整报告区间（可选）</summary>
              {reportKind !== "custom" && <Field label={reportKind === "monthly" ? "所属月份（选择任一天）" : reportKind === "weekly" ? "周报结束日期（含当日共7天）" : "报告日期"}>
                <input
                  type="date"
                  value={reportDate}
                  onChange={(event) => setReportDate(event.target.value)}
                />
              </Field>}
            <Field label="报告周期">
              <select value={reportKind} onChange={(event) => setReportKind(event.target.value as ReportKind)}>
                {([["daily", "日报"], ["weekly", "周报（连续7天）"], ["monthly", "月报（自然月）"], ["custom", "自定义区间"]] as const).filter(([kind]) => !scene || scene.adapter.supported_reports.includes(kind)).map(([kind, label]) => <option key={kind} value={kind}>{label}</option>)}
              </select>
            </Field>
            {reportKind === "custom" && <div className="wb-row">
              <Field label="区间开始日期"><input type="date" value={periodStart} onChange={(event) => setPeriodStart(event.target.value)} /></Field>
              <Field label="区间结束日期"><input type="date" value={periodEnd} onChange={(event) => setPeriodEnd(event.target.value)} /></Field>
            </div>}
            {reportKind !== "daily" && <p className="wb-hint">区间含首尾日，最多366天；保留必要历史计算，缺测不补值。月报覆盖所选日期所在完整自然月。多日预警将触发AI模式的追加规范核查。</p>}
            </details>
          </section>

          <section className="wb-card">
            <div className="wb-card-head">
              <span className="wb-step">2</span>
              <h2>监测数据</h2>
            </div>
            <p className="wb-hint">
              必填 5 列：测点编号 / 观测日期 / 监测项目 / 本次观测值 / 单位。
              基准值、上次值、间隔天数<strong>可缺失</strong>，由阶段一按测点时序派生。
              支持 CSV / TSV / XLSX，自动探测 UTF-8、GBK 等编码。
            </p>
            <div className="wb-actions">
              <a className="wb-btn wb-btn-sm" href="/api/monitoring-files/sample" download>
                <Download size={14} aria-hidden="true" />
                下载示例数据
              </a>
            </div>
            <Field label="选择本工程已上传的监测数据">
              <select value={monitoring?.file.file_id ?? ""} onChange={event => {
                const file = files.find(f => f.file_id === event.target.value);
                setMonitoring(file ? { file, read_report: null } : null); setAdditionalFileIds([]); setResult(null); setParentRunId(null);
              }}>
                <option value="">请选择，或上传新文件</option>
                {files.map(file => <option key={file.file_id} value={file.file_id}>{file.original_name} · {file.uploaded_by?.name ?? "历史上传"} · {file.created_at.slice(0, 10)}</option>)}
              </select>
            </Field>
            {monitoring && <details className="wb-accordion">
              <summary>追加成员文件，统一生成报告 · 已选 {1 + additionalFileIds.length} 份</summary>
              <p className="wb-hint">共用当前工程条件，最多10份。跨文件重复观测或通道口径冲突需核对来源后再生成。</p>
              {files.filter(file => file.file_id !== monitoring.file.file_id).map(file =>
                <label className="wb-checkbox" key={file.file_id}>
                  <input type="checkbox" checked={additionalFileIds.includes(file.file_id)}
                    disabled={!additionalFileIds.includes(file.file_id) && additionalFileIds.length >= 9}
                    onChange={event => setAdditionalFileIds(current => event.target.checked
                      ? [...current, file.file_id] : current.filter(id => id !== file.file_id))} />
                  {file.original_name} · {file.uploaded_by?.name ?? "历史上传"}
                </label>,
              )}
            </details>}
            <div className="wb-drop">
              <input
                id="wb-file"
                type="file"
                aria-label="上传监测数据文件"
                accept=".csv,.tsv,.txt,.xlsx,.xlsm"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void uploadMonitoring(file);
                  event.target.value = "";
                }}
              />
              <label htmlFor="wb-file">
                {busy === "upload" ? (
                  <Loader2 size={15} className="wb-spin" aria-hidden="true" />
                ) : (
                  <FileUp size={15} aria-hidden="true" />
                )}
                {busy === "upload" ? "解析中…" : "选择监测数据文件"}
              </label>
              <p>上限 20 MB；文件保存后立即返回解析报告</p>
            </div>

            {monitoring && (
              <>
                <div className="wb-meta">
                  <span className="wb-chip">{monitoring.file.original_name}</span>
                  <span className="wb-chip">{(monitoring.file.size_bytes / 1024).toFixed(1)} KB</span>
                  <span className="wb-chip">指纹 {monitoring.file.sha256.slice(0, 8)}</span>
                  {monitoring.read_report?.encoding && (
                    <span className="wb-chip">编码 {monitoring.read_report.encoding}</span>
                  )}
                  {monitoring.read_report?.data_rows !== undefined && (
                    <span className="wb-chip">数据行 {monitoring.read_report.data_rows}</span>
                  )}
                </div>
                {monitoring.read_report && (
                  <div className={`wb-alert ${monitoring.read_report.ok ? "wb-alert-ok" : "wb-alert-error"}`}>
                    {monitoring.read_report.ok ? (
                      <CheckCircle2 size={16} aria-hidden="true" />
                    ) : (
                      <AlertTriangle size={16} aria-hidden="true" />
                    )}
                    <div>
                      {monitoring.read_report.ok
                        ? `列映射成功：${Object.values(monitoring.read_report.mapped_columns ?? {}).join("、")}`
                        : (monitoring.read_report.errors ?? []).join("；")}
                      {(monitoring.read_report.unmapped_columns ?? []).length > 0 && (
                        <div>未识别的列：{(monitoring.read_report.unmapped_columns ?? []).join("、")}</div>
                      )}
                      {(monitoring.read_report.derivable_columns_present ?? []).length === 0 && (
                        <div>未提供派生列，将由引擎按测点时序自动派生。</div>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
          </section>

          {session?.authenticated && <ProjectStandards projectId={session.project_id} canReview={canReview} disabled={busy !== null || !canWrite}
            usesProjectControls={scene?.engineering_type?.id==='tunnel'} onBusyChange={active => { operation.current = active; setBusy(active ? "project-standard" : null); }} />}
          {scene?.engineering_type?.id==='foundation_pit'&&<section className="wb-card">
            <div className="wb-card-head">
              <span className="wb-step">3</span>
              <h2>用户规范 JSON（数值阈值，可选）</h2>
            </div>
            <p className="wb-hint">
              不上传时使用默认规范库，<strong>不作任何特殊处理</strong>。上传后按字段级覆盖默认值，
              系统会逐项比较严格程度，凡是<strong>比默认更宽松</strong>的都会列出差异与默认值的规范条文依据。
            </p>
            <Field label="选择本工程已有阈值文件">
              <select value={selectedStandardId ?? ""} onChange={event => { setSelectedStandardId(event.target.value || null); setStandard(null); }}>
                <option value="">使用默认阈值库</option>
                {standardFiles.map(file => <option key={file.file_id} value={file.file_id}>{file.original_name}</option>)}
              </select>
            </Field>
            <Field label="用户规范 JSON">
              <textarea
                value={standardText}
                onChange={(event) => setStandardText(event.target.value)}
                placeholder={'{\n  "source_id": "USER-2026",\n  "source_label": "XX企业工程监测要求",\n  "metrics": { "wall_top_horizontal_displacement": { "rules": [ … ] } }\n}'}
              />
            </Field>
            <div className="wb-actions">
              <input
                id="wb-standard-file"
                type="file"
                accept=".json"
                style={{ display: "none" }}
                onChange={async (event) => {
                  const file = event.target.files?.[0];
                  if (file) setStandardText(await file.text());
                  event.target.value = "";
                }}
              />
              <label className="wb-btn wb-btn-sm" htmlFor="wb-standard-file">
                <Upload size={14} aria-hidden="true" />
                选择 JSON 文件
              </label>
              <button
                className="wb-btn wb-btn-sm"
                type="button"
                onClick={() => void uploadStandard()}
                disabled={busy === "standard" || !standardText.trim()}
              >
                {busy === "standard" ? (
                  <Loader2 size={14} className="wb-spin" aria-hidden="true" />
                ) : (
                  <Upload size={14} aria-hidden="true" />
                )}
                上传并校验
              </button>
              {selectedStandardId && (
                <button
                  className="wb-btn wb-btn-sm"
                  type="button"
                  onClick={() => {
                    setStandard(null);
                    setSelectedStandardId(null);
                    reset();
                  }}
                >
                  移除（改用默认库）
                </button>
              )}
            </div>
            {selectedStandardId && !standard && <p className="wb-hint">已恢复原用户规范引用 {selectedStandardId.slice(0, 8)}；更宽松差异见原运行结果。</p>}

            {standard && (
              <>
                <div className="wb-meta">
                  <span className="wb-chip">{standard.file.original_name}</span>
                  <span className="wb-chip">比较项 {standard.strictness.checked}</span>
                  <span
                    className={`wb-chip${standard.strictness.has_looser ? " wb-chip-warn" : ""}`}
                  >
                    更宽松 {standard.strictness.looser_count}
                  </span>
                  <span className="wb-chip">不可比 {standard.strictness.incomparable_count}</span>
                </div>
                {standard.report ? (
                  <div className="wb-alert wb-alert-warn" style={{ marginTop: 12 }}>
                    <ShieldAlert size={16} aria-hidden="true" />
                    <pre style={{ margin: 0 }}>{standard.report}</pre>
                  </div>
                ) : (
                  <div className="wb-alert wb-alert-ok" style={{ marginTop: 12 }}>
                    <CheckCircle2 size={16} aria-hidden="true" />
                    <div>未发现比默认规范更宽松的阈值。</div>
                  </div>
                )}
              </>
            )}
          </section>}

          <section className="wb-card">
            <div className="wb-card-head">
              <span className="wb-step">4</span>
              <h2>运行分析</h2>
            </div>
            <p className="wb-hint">
              阶段一 数据准备 → 阶段二 确定性计算 → 阶段三 规范比对。
              AI 日报继续执行模型规划、规范检索、报告写作与独立语义审计。
            </p>
            <label className="wb-report-toggle">
              <input type="checkbox" checked={generateReport} onChange={(event) => setGenerateReport(event.target.checked)} />
              生成并审计日报三件套
            </label>
            {generateReport && (
              <Field label="日报生成方式">
                <select value={reportMode} onChange={(event) => setReportMode(event.target.value as "ai" | "template")}>
                  <option value="ai">AI分析与独立审查</option>
                  <option value="template">仅模板：计算结果与附表</option>
                </select>
              </Field>
            )}
            <div className="wb-actions">
              <button
                className="wb-btn wb-btn-primary"
                type="button"
                onClick={() => void runAnalysis()}
                disabled={busy !== null || !monitoring}
              >
                {busy === "run" ? (
                  <Loader2 size={15} className="wb-spin" aria-hidden="true" />
                ) : (
                  <Play size={15} aria-hidden="true" />
                )}
                {busy === "run" ? "计算中…" : "运行分析"}
              </button>
              {(monitoring || result) && (
                <button
                  className="wb-btn"
                  type="button"
                  onClick={() => {
                    setResult(null);
                    setMonitoring(null);
                    setStandard(null);
                    setSelectedStandardId(null);
                    setRerunInput(null);
                    setParentRunId(null);
                    setStandardText("");
                    reset();
                  }}
                >
                  清空
                </button>
              )}
            </div>
          </section>
          </fieldset>
        </div>

        {/* ---------------- 右列：结果 ---------------- */}
        <div className="wb-col">
          {result?.record && <RunDelivery key={`${result.record.run_id}:${result.record.revision}`} record={result.record} disabled={busy !== null} canReviewRole={canReview} canWrite={canWrite}
            onReview={(decision, reason, evaluations) => void perform("review", () => review(decision, reason, evaluations))}
            onSaveEvaluations={(evaluations, reason) => void perform("evaluation", () => saveEvaluations(evaluations, reason))}
            onDownload={(url, fileName) => void perform("download", () => download(url, fileName))}
            onLoadInputs={() => void perform("inputs", loadInputs)}
            onResume={() => void perform("resume", async () => {
              const response = await apiFetch(`/api/runs/${result.record.run_id}/resume`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ expected_revision: result.record.revision }),
              });
              if (!response.ok) throw new Error(await readError(response));
              setResult(await response.json() as RunResponse);
              await refreshHistory();
            })} />}
          {!result && (
            <section className="wb-card">
              <div className="wb-empty">
                <h3>还没有分析结果</h3>
                <p>
                  点击左侧「下载示例数据」拿到一份可直接用的 CSV，
                  <br />
                  上传后点「运行分析」即可看到确定性计算与风险识别结果。
                </p>
              </div>
            </section>
          )}

          {result && payload && (
            <>
              {payload.period && <section className="wb-card" aria-label="周期报告汇总">
                <div className="wb-card-head"><h2>{payload.period.label} · 阶段风险与覆盖</h2></div>
                <p>{payload.period.start_date} 至 {payload.period.end_date}（含首尾日）</p>
                <p>日历 {payload.period.calendar_days} 天 · 有观测 {payload.period.observed_days} 天 · {payload.period.channel_count} 通道 · 预警及以上 {payload.period.warning_point_days} 点日 · 未知 {payload.period.unknown_observation_count} 条</p>
                <p className="wb-hint">附表为周期最严重原观测，不是期末值。未知、缺测不代表正常；宽表按每日末值，日内极值仍需结合原数据复核。</p>
                {payload.period.missing_dates.length > 0 && <p className="wb-hint">整日缺测：{payload.period.missing_dates.join("、")}</p>}
                {payload.period.recurring_warnings.map((item) => <p key={`${item.point_id}:${item.metric_name}`}>
                  {item.point_id} · {item.metric_name}：预警及以上 {item.warning_days} 天，最长连续 {item.max_consecutive_warning_days} 天。
                </p>)}
                <details className="wb-accordion"><summary>每日风险变化与缺口</summary>
                  {payload.period.daily_summaries.map((day) => <p key={day.date}>{day.date}：{day.missing ? "缺测，不能判为正常" : `${day.observation_count}条观测，预警及以上${day.warning_count}条，未知${day.unknown_count}条，最严重已知等级${day.worst_known_risk}`}</p>)}
                </details>
              </section>}
              <section className="wb-card">
                <div className="wb-card-head">
                  <h2>总览</h2>
                </div>
                <div className="wb-kpis">
                  <div className="wb-kpi">
                    <span>总体风险等级</span>
                    <strong>
                      <LevelBadge level={payload.summary?.overall_risk_level} />
                    </strong>
                  </div>
                  <div className="wb-kpi">
                    <span>判定条目</span>
                    <strong>{payload.summary?.total ?? 0}</strong>
                  </div>
                  <div className="wb-kpi">
                    <span>报警及以上</span>
                    <strong>{payload.alerts?.length ?? 0}</strong>
                  </div>
                  <div className="wb-kpi">
                    <span>待人工复核</span>
                    <strong>{payload.review_queue?.length ?? 0}</strong>
                  </div>
                  <div className="wb-kpi">
                    <span>数据质量阻塞</span>
                    <strong>{payload.data_quality?.blocked_records ?? 0}</strong>
                  </div>
                  <div className="wb-kpi">
                    <span>引擎耗时</span>
                    <strong>{num(result.engine?.elapsed_ms, 0)} ms</strong>
                  </div>
                </div>
                <div className="wb-meta">
                  <span className="wb-chip">
                    生效阈值来源：
                    {payload.context?.effective_standard_origin === "user_uploaded"
                      ? "用户上传规范"
                      : "默认规范库"}
                  </span>
                  <span className="wb-chip">阶段三 · 规范比对</span>
                  {result.engine?.python && <span className="wb-chip">Python {result.engine.python}</span>}
                  <span className="wb-chip">运行 {result.run_id?.slice(0, 8)}</span>
                </div>

                <div className="wb-dist" style={{ marginTop: 18 }}>
                  {LEVEL_ORDER.filter((level) => (byLevel[level] ?? 0) > 0).map((level) => (
                    <div className="wb-dist-row" key={level}>
                      <LevelBadge level={level} />
                      <span className="wb-bar">
                        <i
                          className={`wb-level-${LEVEL_KEY[level]}`}
                          style={{ width: `${((byLevel[level] ?? 0) / maxLevelCount) * 100}%` }}
                        />
                      </span>
                      <span className="wb-num">{byLevel[level]}</span>
                    </div>
                  ))}
                </div>
              </section>

              {(payload.standard_override_warnings?.length ?? 0) > 0 && (
                <section className="wb-card">
                  <div className="wb-card-head">
                    <ShieldAlert size={16} aria-hidden="true" />
                    <h2>用户阈值比默认规范更宽松</h2>
                  </div>
                  <p className="wb-hint">
                    更宽松的阈值会降低报警灵敏度，可能造成漏判。若该阈值来自经设计方确认的地方规程或
                    项目专项方案，请在日报中注明；否则建议采用默认规范值。
                  </p>
                  {payload.standard_override_warnings?.map((warning, index) => (
                    <div className="wb-alert wb-alert-warn" key={`${warning.metric_key}-${index}`}>
                      <div>
                        <strong>{warning.metric_name}</strong>
                        {warning.differences?.map((diff, diffIndex) => (
                          <div key={diffIndex} style={{ marginTop: 6 }}>
                            {diff.field_display}：用户 {num(diff.user_value)}
                            {diff.unit} ← 默认 {num(diff.default_value)}
                            {diff.unit}（放宽 {num(diff.delta_pct, 1)}%，{diff.severity}）
                            <span className="wb-basis">
                              默认依据：{diff.default_evidence?.standard} {diff.default_evidence?.clause}
                              {diff.default_basis ? `（${diff.default_basis}）` : ""}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </section>
              )}

              <section className="wb-card">
                <div className="wb-card-head">
                  <h2>报警清单（报警及以上）</h2>
                </div>
                {(payload.alerts?.length ?? 0) === 0 ? (
                  <div className="wb-empty">
                    <p>无报警及以上条目。</p>
                  </div>
                ) : (
                  <div className="wb-table-wrap wb-scroll">
                    <table className="wb-table">
                      <thead>
                        <tr>
                          <th>测点</th>
                          <th>监测项</th>
                          <th>时间</th>
                          <th className="wb-num">累计</th>
                          <th className="wb-num">速率</th>
                          <th className="wb-num">利用率</th>
                          <th>等级</th>
                          <th>依据</th>
                        </tr>
                      </thead>
                      <tbody>
                        {payload.alerts?.map((item, index) => (
                          <tr key={`${item.point_id}-${item.timestamp}-${item.metric_key}-${index}`}>
                            <td>{item.point_id}</td>
                            <td>
                              {item.metric_name}
                              <span className="wb-basis">{item.problem_category}</span>
                            </td>
                            <td className="wb-mono">{item.timestamp}</td>
                            <td className="wb-num">{num(item.cumulative)}</td>
                            <td className="wb-num">{num(item.rate, 3)}</td>
                            <td className="wb-num">{num(item.utilization, 3)}</td>
                            <td>
                              <LevelBadge level={item.risk_level} />
                            </td>
                            <td>
                              {item.evidence?.standard} {item.evidence?.clause}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              <section className="wb-card">
                <div className="wb-card-head">
                  <h2>待人工复核（弃权项）</h2>
                </div>
                <p className="wb-hint">
                  「未知」表示<strong>弃权，不是「安全」</strong>。缺 H、缺判据、数据质量问题都会进入这里，必须转人工复核。
                </p>
                {(payload.review_queue?.length ?? 0) === 0 ? (
                  <div className="wb-empty">
                    <p>无待复核条目。</p>
                  </div>
                ) : (
                  <div className="wb-table-wrap wb-scroll">
                    <table className="wb-table">
                      <thead>
                        <tr>
                          <th>测点</th>
                          <th>监测项</th>
                          <th>时间</th>
                          <th>弃权原因</th>
                          <th>等级</th>
                        </tr>
                      </thead>
                      <tbody>
                        {payload.review_queue?.slice(0, 200).map((item, index) => (
                          <tr key={`${item.point_id}-${item.timestamp}-${index}`}>
                            <td>{item.point_id}</td>
                            <td>{item.metric_name}</td>
                            <td className="wb-mono">{item.timestamp}</td>
                            <td>
                              {(item.abstain_reasons ?? []).join("；") || (item.abstain ?? []).join("、")}
                            </td>
                            <td>
                              <LevelBadge level={item.risk_level} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {(payload.review_queue?.length ?? 0) > 200 && (
                  <p className="wb-hint">仅显示前 200 条，完整内容见下方载荷。</p>
                )}
              </section>

              <section className="wb-card">
                <div className="wb-card-head">
                  <h2>逐测点明细</h2>
                </div>
                <div className="wb-table-wrap wb-scroll">
                  <table className="wb-table">
                    <thead>
                      <tr>
                        <th>测点</th>
                        <th>监测项</th>
                        <th>时间</th>
                        <th className="wb-num">本次值</th>
                        <th className="wb-num">累计</th>
                        <th className="wb-num">变化量</th>
                        <th className="wb-num">速率</th>
                        <th className="wb-num">限值</th>
                        <th className="wb-num">利用率</th>
                        <th>等级</th>
                      </tr>
                    </thead>
                    <tbody>
                      {payload.items?.slice(0, 300).map((item, index) => {
                        const cumulativeCheck = (item.checks ?? []).find((check) =>
                          String(check.check ?? "").startsWith("累计值"),
                        );
                        return (
                          <tr key={`${item.point_id}-${item.timestamp}-${item.metric_key}-${index}`}>
                            <td>{item.point_id}</td>
                            <td>
                              {item.metric_name}
                              {item.rule_id && <span className="wb-basis">{item.rule_id}</span>}
                            </td>
                            <td className="wb-mono">{item.timestamp}</td>
                            <td className="wb-num">{num(item.current)}</td>
                            <td className="wb-num">{num(item.cumulative)}</td>
                            <td className="wb-num">{num(item.single_change)}</td>
                            <td className="wb-num">{num(item.rate, 3)}</td>
                            <td className="wb-num">
                              {cumulativeCheck ? num(cumulativeCheck.limit) : "—"}
                              {cumulativeCheck?.limit_is_upper_bound ? (
                                <span className="wb-basis">（上界）</span>
                              ) : null}
                            </td>
                            <td className="wb-num">{num(item.utilization, 3)}</td>
                            <td>
                              <LevelBadge level={item.risk_level} />
                              {item.needs_review && <span className="wb-basis">待复核</span>}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {(payload.items?.length ?? 0) > 300 && (
                  <p className="wb-hint">仅显示前 300 条，完整内容见下方载荷。</p>
                )}
              </section>

              <section className="wb-card">
                <div className="wb-card-head">
                  <h2>数据质量与规范来源</h2>
                </div>
                <div className="wb-meta">
                  <span className="wb-chip">质量问题 {payload.data_quality?.issue_count ?? 0} 处</span>
                  <span className="wb-chip">阻塞期次 {payload.data_quality?.blocked_records ?? 0}</span>
                  <span className="wb-chip">真实记录 {String(payload.context?.real_records ?? "—")}</span>
                  <span className="wb-chip">模拟记录 {String(payload.context?.simulated_records ?? "—")}</span>
                </div>
                {Object.keys(payload.data_quality?.by_code ?? {}).length > 0 && (
                  <div className="wb-meta">
                    {Object.entries(payload.data_quality?.by_code ?? {}).map(([code, count]) => (
                      <span className="wb-chip wb-chip-warn" key={code}>
                        {code} × {count}
                      </span>
                    ))}
                  </div>
                )}
                <div className="wb-meta">
                  {(payload.standards_sources ?? []).map((source, index) => (
                    <span className="wb-chip" key={index}>
                      {String(source.source_label ?? source.source_id ?? "规范来源")}
                      {source.metric_count !== undefined ? `（${source.metric_count} 项）` : ""}
                    </span>
                  ))}
                </div>
                {payload.disclaimer && (
                  <div className="wb-alert wb-alert-info" style={{ marginTop: 14, marginBottom: 0 }}>
                    <ShieldAlert size={16} aria-hidden="true" />
                    <div>{payload.disclaimer}</div>
                  </div>
                )}

                <details className="wb-accordion">
                  <summary>查看 / 下载原始载荷（excavaguard.daily_report_input/v1）</summary>
                  <div className="wb-actions">
                    <button
                      className="wb-btn wb-btn-sm"
                      type="button"
                      onClick={() => {
                        const blob = new Blob([JSON.stringify(result, null, 2)], {
                          type: "application/json",
                        });
                        const url = URL.createObjectURL(blob);
                        const anchor = document.createElement("a");
                        anchor.href = url;
                        anchor.download = `excavaguard-run-${result.run_id?.slice(0, 8) ?? "result"}.json`;
                        anchor.click();
                        URL.revokeObjectURL(url);
                      }}
                    >
                      <Download size={14} aria-hidden="true" />
                      下载 JSON
                    </button>
                  </div>
                  <pre>{JSON.stringify(result, null, 2)}</pre>
                </details>
              </section>
            </>
          )}
        </div>
      </div>
    </>
  );
}
