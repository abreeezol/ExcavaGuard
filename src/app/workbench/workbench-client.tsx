"use client";
import { ProjectStandards } from "./project-standards";
import { ReportRangeDialog } from "./report-range-dialog";
import { latestSuccessfulRun, reportRangeLabel, resolveReportRange, type ReportRange } from "./report-range";
import { RunConditions } from "./run-conditions";
import type { WorkbenchStep } from "@/components/workspace-sidebar";

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
import type { ReportKind } from "@/contracts/report-period";
import { listFilesResponseSchema, type ReadReport, type StoredFile, type StrictnessReport } from "@/contracts/monitoring-files";
import type { AccessStatus } from "@/contracts/access";
import type { CreateRunRequest, PersistedRun, ReviewRequest, RunSummary } from "@/contracts/runs";
import { persistedRunSchema, runListResponseSchema } from "@/contracts/runs";
import type { EngineerRiskEvaluationInput } from "@/contracts/engineer-evaluation";
import { decisionLabel, executionLabel, RunDelivery } from "./run-delivery";

/**
 * 工程监测工作台（客户端）
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

export function ProjectWorkbench({ session, onBusyChange, onDirtyChange, step, onStepChange, onDefaultStep, initialRunId, sessionPending }: {
  session: AccessStatus & { project_id: string }; onBusyChange: (busy: boolean) => void;
  onDirtyChange: (dirty: boolean) => void;
  step: WorkbenchStep;
  onStepChange: (step: WorkbenchStep, runId?: string | null) => void;
  onDefaultStep: (step: WorkbenchStep, runId?: string) => void;
  initialRunId: string | null;
  sessionPending: boolean;
}) {
  const project = session.projects?.find(p => p.id === session.project_id);
  const canWrite = Boolean(project && project.role !== "viewer");
  const canReview = Boolean(project && ["admin", "reviewer"].includes(project.role));
  const canDelete = project?.role === "admin";
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [standardFiles, setStandardFiles] = useState<StoredFile[]>([]);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
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
  const dirty = useRef(false);
  const initialized = useRef(false);
  const rangePrompted = useRef(false);
  const requestController = useRef<AbortController | null>(null);
  const [safetyLevel, setSafetyLevel] = useState<"" | "一级" | "二级" | "三级">("");
  const [supportType, setSupportType] = useState("");
  const [depthInput, setDepthInput] = useState("");
  const [postSlabFrom, setPostSlabFrom] = useState("");
  const [projectName, setProjectName] = useState(project?.name ?? "");
  const [reportDate, setReportDate] = useState("");
  const [reportKind, setReportKind] = useState<ReportKind>("daily");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [rangeConfirmed, setRangeConfirmed] = useState(false);
  const [rangeDialogOpen, setRangeDialogOpen] = useState(false);
  const [resultInfoOpen, setResultInfoOpen] = useState(true);
  const range: ReportRange = { kind: reportKind, date: reportDate, start: periodStart, end: periodEnd };
  const rangeSummary = rangeConfirmed ? reportRangeLabel(range) : "尚未选择报告范围";
  const notifyDirty = useCallback((value: boolean) => {
    dirty.current = value;
    onDirtyChange(value);
  }, [onDirtyChange]);

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
    return fetch(url, { ...init, headers, signal: requestController.current?.signal, cache: "no-store" });
  }, [session.project_id]);
  useEffect(() => {
    const query = window.matchMedia("(max-width: 760px)");
    const update = () => setResultInfoOpen(!query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    requestController.current = controller;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (dirty.current || operation.current) event.preventDefault();
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => {
      controller.abort();
      onDirtyChange(false);
      window.removeEventListener("beforeunload", beforeUnload);
    };
  }, [onDirtyChange]);
  useEffect(() => {
    if (step === "conditions" && !rangeConfirmed && !rangePrompted.current && canWrite) {
      rangePrompted.current = true;
      setRangeDialogOpen(true);
    }
  }, [step, rangeConfirmed, canWrite]);
  useEffect(() => { onBusyChange(busy !== null); }, [busy, onBusyChange]);
  useEffect(() => {
    if (initialized.current) return;
    let cancelled = false;
    operation.current = true;
    setBusy("history");
    setHistoryError(null);
    void (async () => {
      try {
        const responses = await Promise.all([apiFetch("/api/runs"), apiFetch("/api/monitoring-files"), apiFetch("/api/standards")]);
        for (const response of responses) if (!response.ok) throw new Error(await readError(response));
        const [runs, monitoringFiles, standards] = await Promise.all(responses.map(response => response.json()));
        if (!cancelled) {
          const summaries = runListResponseSchema.parse(runs).runs;
          setHistory(summaries);
          setFiles(listFilesResponseSchema.parse(monitoringFiles).files);
          setStandardFiles(listFilesResponseSchema.parse(standards).files);
          const candidates = [...summaries];
          let runId = initialRunId ?? latestSuccessfulRun(candidates)?.run_id;
          let restored = false;
          while (runId && !cancelled) {
            const response = await apiFetch(`/api/runs/${encodeURIComponent(runId)}`);
            if (!response.ok) throw new Error(await readError(response));
            const body = await response.json() as RunResponse;
            persistedRunSchema.parse(body.record);
            if (cancelled) return;
            if (initialRunId || body.record.result) {
              setResult(body);
              onDefaultStep("results", body.record.run_id);
              restored = true;
              break;
            }
            candidates.splice(candidates.findIndex(item => item.run_id === runId), 1);
            runId = latestSuccessfulRun(candidates)?.run_id;
          }
          if (!cancelled) {
            initialized.current = true;
            if (!restored) onDefaultStep("conditions");
          }
        }
      } catch (caught) {
        if (!cancelled) setHistoryError(caught instanceof Error ? caught.message : "加载项目失败。");
      } finally {
        if (!cancelled) { operation.current = false; setBusy(null); }
      }
    })();
    return () => { cancelled = true; };
  }, [apiFetch, initialRunId, onDefaultStep, loadAttempt]);
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
    if (operation.current || sessionPending) return false;
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
    if (!confirmReplaceReview()) return;
    const response = await apiFetch(`/api/runs/${encodeURIComponent(runId)}`);
    if (!response.ok) {
      if (response.status === 404 && result?.record.run_id === runId) { notifyDirty(false); setResult(null); }
      throw new Error(await readError(response));
    }
    const body = await response.json() as RunResponse;
    persistedRunSchema.parse(body.record);
    notifyDirty(false);
    setResult(body);
    onStepChange("results", body.record.run_id);
    setRemoteRevision(null);
  }

  async function deleteHistory(run: RunSummary) {
    if (result?.record.run_id === run.run_id && !confirmReplaceReview()) return;
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
    if (result?.record.run_id === run.run_id) { notifyDirty(false); setResult(null); onStepChange("results", null); }
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
    const files = listFilesResponseSchema.parse(await response.json()).files;
    const file = files.find((file) => file.file_id === record.request.monitoring_file_id);
    const input = record.request;
    const additional = record.request.additional_monitoring_file_ids ?? [];
    const availableAdditional = additional.filter(id => files.some(file => file.file_id === id));
    const missingFiles = !file || availableAdditional.length !== additional.length;
    setMonitoring(!missingFiles && file ? { file, read_report: (record.result?.read_report as ReadReport | null) ?? null } : null);
    setFiles(files);
    setAdditionalFileIds(missingFiles ? [] : availableAdditional);
    setSafetyLevel(input.context.safety_level);
    setSupportType(input.context.support_type);
    setDepthInput(input.context.excavation_depth_m?.toString() ?? "");
    setPostSlabFrom(input.context.post_slab_from ?? "");
    setProjectName(project?.name ?? input.project?.name ?? "");
    setReportDate(input.report_date);
    setReportKind(input.report_period?.type ?? "daily");
    setPeriodStart(input.report_period?.start_date ?? input.report_date);
    setPeriodEnd(input.report_period?.end_date ?? input.report_date);
    setRangeConfirmed(true);
    rangePrompted.current = true;
    setGenerateReport(input.options?.generate_report ?? true);
    setReportMode(input.options?.report_mode ?? "ai");
    setSelectedStandardId(input.standards_file_id ?? null);
    setStandard(null);
    setStandardText("");
    setRerunInput({ ...input, project_standard_ids: input.project_standard_ids ??
      record.result?.project_standards?.map(document => document.document_id) ?? [] });
    setParentRunId(record.run_id);
    onStepChange("conditions");
    setNotice(`已加载 ${record.run_id.slice(0, 8)} 的工程条件及规范引用，后续分析将创建关联运行。${missingFiles
      ? "原监测文件或部分汇总文件已不可用，请在数据与规范中重新选择或上传所需文件。" : "请核对输入后运行分析。"}`);
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
    notifyDirty(false);
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
    notifyDirty(false);
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

  const depth = depthInput.trim() === "" ? null : Number(depthInput);
  const depthValid = depth === null || (Number.isFinite(depth) && depth > 0 && depth <= 200);

  function reset() {
    setError(null);
    setNotice(null);
  }

  function confirmReplaceReview() {
    return !dirty.current || window.confirm("当前报告有未保存的评价或总评，继续会替换这些内容。确认继续？");
  }

  function startNewReport() {
    if (operation.current || !canWrite) return;
    setMonitoring(null);
    setAdditionalFileIds([]);
    setStandard(null);
    setSelectedStandardId(null);
    setStandardText("");
    setRerunInput(null);
    setParentRunId(null);
    setSafetyLevel("");
    setSupportType("");
    setDepthInput("");
    setPostSlabFrom("");
    setReportDate("");
    setPeriodStart("");
    setPeriodEnd("");
    setReportKind("daily");
    setRangeConfirmed(false);
    rangePrompted.current = false;
    reset();
    onStepChange("conditions");
  }

  async function uploadMonitoring(file: File) {
    if (!begin("upload")) return;
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
    if (!canWrite || !safetyLevel || !supportType || !depthValid) {
      setError("请先在工程条件中确认判据适用条件，并检查设计深度。");
      return;
    }
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
          context: { safety_level: safetyLevel, support_type: supportType, excavation_depth_m: depth },
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
    if (!canWrite || !rangeConfirmed || !safetyLevel || !supportType) {
      setError("请先确认报告范围与判据适用条件。");
      return;
    }
    if (!monitoring) {
      setError("请先上传监测数据文件。");
      return;
    }
    if (!depthValid) {
      setError("基坑设计深度需为 0~200 之间的数字，或留空表示暂未提供。");
      return;
    }
    let reportPeriod;
    try {
      reportPeriod = resolveReportRange(range).report_period;
    } catch {
      setError("请检查报告起止日期：起始日不得晚于结束日，区间最多366天。");
      return;
    }
    if (!confirmReplaceReview()) return;
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
          project_standard_ids: rerunInput?.project_standard_ids,
          report_date: reportPeriod?.end_date ?? reportDate,
          report_period: reportPeriod,
          context: {
            ...rerunInput?.context,
            safety_level: safetyLevel,
            support_type: supportType,
            excavation_depth_m: depth,
            post_slab_from: postSlabFrom.trim() || null,
          },
          project: projectName.trim() ? { ...rerunInput?.project, name: projectName.trim() } : undefined,
          options: { ...rerunInput?.options, generate_report: generateReport, report_mode: reportMode },
        }),
      });
      if (!response.ok) {
        setError(await readError(response));
        return;
      }
      const body = await response.json() as RunResponse;
      persistedRunSchema.parse(body.record);
      notifyDirty(false);
      setResult(body);
      onStepChange("results", body.record.run_id);
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
      {rangeDialogOpen && <ReportRangeDialog initial={rangeConfirmed ? range : null}
        onClose={() => setRangeDialogOpen(false)} onConfirm={next => {
          setReportKind(next.kind);
          setReportDate(next.date);
          setPeriodStart(next.start);
          setPeriodEnd(next.end);
          setRangeConfirmed(true);
          setRangeDialogOpen(false);
        }} />}
      <div hidden={step === "start"}>
      {step === "results" && canWrite && <div className="wb-actions wb-stage-actions">
        <button className="wb-btn wb-btn-primary" disabled={busy !== null} onClick={startNewReport}>新建报告</button>
      </div>}
      {historyError && <div role="alert" className="wb-alert wb-alert-error">
        <div>工程资料或历史加载失败：{historyError}
          <div className="wb-actions">
            <button className="wb-btn wb-btn-sm" disabled={busy !== null} onClick={() => setLoadAttempt(value => value + 1)}>重试加载</button>
            {canWrite && <button className="wb-btn wb-btn-sm" disabled={busy !== null} onClick={startNewReport}>开始新报告</button>}
          </div>
        </div>
      </div>}

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

      <div className={`wb-grid wb-stage-${step}`}>
        <div className="wb-col wb-result-context" hidden={step !== "results"}>
          <details className="wb-result-info" open={resultInfoOpen} onToggle={event => setResultInfoOpen(event.currentTarget.open)}>
            <summary>工程条件与运行历史</summary>
            {result && <RunConditions record={result.record} currentName={project?.name} />}
          <section className="wb-card" aria-label="运行历史">
            <div className="wb-card-head"><h2>工程运行历史</h2></div>
            <div className="wb-actions">
              <button className="wb-btn wb-btn-sm" disabled={busy !== null} onClick={() => void perform("history", refreshSharedData)}>刷新历史</button>
              {result && <button className="wb-btn wb-btn-sm" disabled={busy !== null}
                onClick={() => {
                  void perform("history", () => openRun(result.record.run_id));
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
                  void perform("history", () => openRun(result.record.run_id));
                }}>加载最新协作版本</button>
            </div></div>}
            <div className="wb-history">
              {visibleHistory.map((run) => (
                <div className="wb-history-row" key={run.run_id}>
                  <button className="wb-history-item" aria-current={result?.record.run_id === run.run_id ? "true" : undefined}
                    disabled={busy !== null} onClick={() => void perform("history", () => openRun(run.run_id))}>
                    <strong>{reportRangeLabel({ kind: run.report_period?.type ?? "daily", date: run.report_date,
                      start: run.report_period?.start_date ?? run.report_date, end: run.report_period?.end_date ?? run.report_date })}</strong>
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
              {visibleHistory.length === 0 && <p className="wb-hint">{busy === "history" ? "正在加载工程历史…" : historyError ? "历史尚未加载，请重试。" : "暂无符合筛选条件的运行记录。"}</p>}
            </div>
          </section>
          </details>
        </div>
        <div className="wb-col wb-stage-input">
          <fieldset className="wb-inputs" disabled={busy !== null || sessionPending || !canWrite}>
          <section className="wb-card" hidden={step !== "conditions"}>
            <div className="wb-card-head">
              <span className="wb-step">2</span>
              <h2>工程条件</h2>
            </div>
            <p className="wb-hint">
              确认真实工程条件与报告范围。<strong>留空 H 不会放宽判据</strong> ——
              含 %H 的累计值判据会转为弃权并进入人工复核队列。
            </p>
            <div className="wb-row">
              <Field label="安全等级">
                <select
                  value={safetyLevel}
                  onChange={(event) => setSafetyLevel(event.target.value as typeof safetyLevel)}
                >
                  <option value="">请选择实际安全等级</option>
                  <option value="一级">一级</option>
                  <option value="二级">二级</option>
                  <option value="三级">三级</option>
                </select>
              </Field>
              <Field label="工程名称（由当前工程确定）"><input value={projectName} readOnly /></Field>
            </div>
            <div className="wb-row">
              <Field label="基坑设计深度 H（m，可留空）">
                <input
                  value={depthInput}
                  onChange={(event) => setDepthInput(event.target.value)}
                  inputMode="decimal"
                  placeholder="留空 = 暂未提供"
                />
              </Field>
              <Field label="底板浇筑日期（可选）">
                <input
                  type="date"
                  value={postSlabFrom}
                  onChange={(event) => setPostSlabFrom(event.target.value)}
                />
              </Field>
            </div>
            <div className="wb-range-summary">
              <div><h3>报告范围</h3><p>{rangeSummary}</p></div>
              <button className="wb-btn" type="button" onClick={() => setRangeDialogOpen(true)}>{rangeConfirmed ? "修改范围" : "选择范围"}</button>
            </div>
            <details className="wb-accordion">
              <summary>判据适用条件 · {supportType ? `已确认：${supportType}` : "待确认"}</summary>
              <p className="wb-hint">用于匹配实际适用规范，请按工程资料确认。当前计算规则仍针对已有基坑监测范围。</p>
              <Field label="实际支护信息">
                <select value={supportType} onChange={event => setSupportType(event.target.value)}>
                  <option value="">请选择实际条件</option>
                  {supportType && !["地下连续墙", "灌注桩", "钢板桩", "型钢水泥土墙", "土钉墙"].includes(supportType) && <option value={supportType}>{supportType}</option>}
                  <option value="地下连续墙">地下连续墙</option>
                  <option value="灌注桩">灌注桩</option>
                  <option value="钢板桩">钢板桩</option>
                  <option value="型钢水泥土墙">型钢水泥土墙</option>
                  <option value="土钉墙">土钉墙</option>
                </select>
              </Field>
            </details>
            {!depthValid && <p className="wb-hint">基坑设计深度需为 0~200 之间的数字。</p>}
            <div className="wb-actions">
              <button className="wb-btn wb-btn-primary" type="button" onClick={() => onStepChange("data")}>下一步：数据与规范</button>
            </div>
          </section>

          <div className="wb-col" hidden={step !== "data"}>
          <section className="wb-card">
            <div className="wb-card-head">
              <span className="wb-step">3</span>
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
                setMonitoring(file ? { file, read_report: null } : null); setAdditionalFileIds([]);
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

          {session?.authenticated && <ProjectStandards projectId={session.project_id} disabled={busy !== null || sessionPending || !canWrite}
            onBusyChange={active => { operation.current = active; setBusy(active ? "project-standard" : null); }} />}
          <section className="wb-card">
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
                placeholder={'{\n  "source_id": "USER-2026",\n  "source_label": "XX企业基坑监测标准",\n  "metrics": { "wall_top_horizontal_displacement": { "rules": [ … ] } }\n}'}
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
                disabled={busy === "standard" || !standardText.trim() || !safetyLevel || !supportType || !depthValid}
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
          </section>
          <div className="wb-actions">
            <button className="wb-btn" type="button" onClick={() => onStepChange("conditions")}>上一步：工程条件</button>
            <button className="wb-btn wb-btn-primary" type="button" onClick={() => onStepChange("results")}>下一步：分析与复核</button>
          </div>
          </div>

          <section className="wb-card" hidden={step !== "results" || !canWrite || (Boolean(result) && !monitoring)}>
            <div className="wb-card-head">
              <span className="wb-step">4</span>
              <h2>运行分析</h2>
            </div>
            <p className="wb-hint">
              阶段一 数据准备 → 阶段二 确定性计算 → 阶段三 规范比对。
              AI 报告继续执行模型规划、规范检索、报告写作与独立语义审计。
            </p>
            <div className="wb-meta">
              <span className="wb-chip">新任务：{rangeSummary}</span>
              <span className="wb-chip">{monitoring ? `监测文件 ${1 + additionalFileIds.length} 份` : "尚未选择监测文件"}</span>
              <span className="wb-chip">{supportType ? "适用条件已确认" : "适用条件待确认"}</span>
              {parentRunId && <span className="wb-chip">关联原运行 {parentRunId.slice(0, 8)}</span>}
            </div>
            <label className="wb-report-toggle">
              <input type="checkbox" checked={generateReport} onChange={(event) => setGenerateReport(event.target.checked)} />
              生成并审计监测报告三件套
            </label>
            {generateReport && (
              <Field label="报告生成方式">
                <select value={reportMode} onChange={(event) => setReportMode(event.target.value as "ai" | "template")}>
                  <option value="ai">AI 报告：LLM + RAG + 独立审计</option>
                  <option value="template">仅模板：计算结果与附表</option>
                </select>
              </Field>
            )}
            <div className="wb-actions">
              <button
                className="wb-btn wb-btn-primary"
                type="button"
                onClick={() => void runAnalysis()}
                disabled={busy !== null || !monitoring || !rangeConfirmed || !safetyLevel || !supportType || !depthValid || monitoring.read_report?.ok === false}
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
                  onClick={startNewReport}
                >
                  重新填写
                </button>
              )}
            </div>
          </section>
          </fieldset>
        </div>

        {/* ---------------- 右列：结果 ---------------- */}
        <div className="wb-col wb-result-main" hidden={step !== "results"}>
          {result?.record && <RunDelivery key={`${result.record.run_id}:${result.record.revision}`} record={result.record} disabled={busy !== null || sessionPending} canReviewRole={canReview} canWrite={canWrite}
            onDirtyChange={notifyDirty}
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
              const body = await response.json() as RunResponse;
              persistedRunSchema.parse(body.record);
              notifyDirty(false);
              setResult(body);
              await refreshHistory();
            })} />}
          {!result && (
            <section className="wb-card">
              <div className="wb-empty">
                <h3>{busy === "history" ? "正在加载工程成果" : historyError ? "暂未加载分析结果" : "尚无分析结果"}</h3>
                <p>已有报告可从工程历史直接打开；新报告请依次确认工程条件、上传数据并运行分析。</p>
                {canWrite && <button className="wb-btn" disabled={busy !== null} onClick={startNewReport}>开始新报告</button>}
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
      </div>
    </>
  );
}
