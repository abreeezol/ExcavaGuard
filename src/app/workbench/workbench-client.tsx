"use client";

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileUp,
  Loader2,
  Play,
  ShieldAlert,
  Upload,
} from "lucide-react";
import type { ReadReport, StoredFile, StrictnessReport } from "@/contracts/monitoring-files";

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

export function WorkbenchClient() {
  const [safetyLevel, setSafetyLevel] = useState<"一级" | "二级" | "三级">("一级");
  const [supportType, setSupportType] = useState("地下连续墙");
  const [depthInput, setDepthInput] = useState("20");
  const [postSlabFrom, setPostSlabFrom] = useState("");
  const [projectName, setProjectName] = useState("示例基坑工程");
  const [reportDate, setReportDate] = useState("2026-08-07");

  const [monitoring, setMonitoring] = useState<{ file: StoredFile; read_report: ReadReport | null } | null>(null);
  const [standard, setStandard] = useState<{
    file: StoredFile;
    strictness: StrictnessReport;
    report: string;
  } | null>(null);
  const [standardText, setStandardText] = useState("");

  const [result, setResult] = useState<RunResponse | null>(null);
  const [busy, setBusy] = useState<"upload" | "standard" | "run" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const depth = depthInput.trim() === "" ? null : Number(depthInput);
  const depthValid = depth === null || (Number.isFinite(depth) && depth > 0 && depth <= 200);

  function reset() {
    setError(null);
    setNotice(null);
  }

  async function uploadMonitoring(file: File) {
    reset();
    setBusy("upload");
    setResult(null);
    try {
      const form = new FormData();
      form.set("file", file);
      const response = await fetch("/api/monitoring-files", { method: "POST", body: form });
      if (!response.ok) {
        setError(await readError(response));
        return;
      }
      const body = (await response.json()) as { file: StoredFile; read_report: ReadReport | null };
      setMonitoring({ file: body.file, read_report: body.read_report });
      if (body.read_report?.ok === false) {
        setNotice("文件已保存，但缺少必填列，运行分析会被拒绝。请对照下方提示修改后重新上传。");
      }
    } catch (caught) {
      setError(`上传失败：${caught instanceof Error ? caught.message : String(caught)}`);
    } finally {
      setBusy(null);
    }
  }

  async function uploadStandard() {
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
    setBusy("standard");
    try {
      const response = await fetch("/api/standards", {
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
      setNotice(
        body.strictness.has_looser
          ? "用户规范已上传，但存在比默认规范更宽松的阈值，请先阅读下方差异。"
          : "用户规范已上传，未发现比默认规范更宽松的阈值。",
      );
    } catch (caught) {
      setError(`上传规范失败：${caught instanceof Error ? caught.message : String(caught)}`);
    } finally {
      setBusy(null);
    }
  }

  async function runAnalysis() {
    reset();
    if (!monitoring) {
      setError("请先上传监测数据文件。");
      return;
    }
    if (!depthValid) {
      setError("基坑设计深度需为 0~200 之间的数字，或留空表示暂未提供。");
      return;
    }
    setBusy("run");
    try {
      const response = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: "11111111-1111-4111-8111-111111111111",
          monitoring_file_id: monitoring.file.file_id,
          standards_file_id: standard?.file.file_id ?? null,
          report_date: reportDate,
          context: {
            safety_level: safetyLevel,
            support_type: supportType,
            excavation_depth_m: depth,
            post_slab_from: postSlabFrom.trim() || null,
          },
          project: projectName.trim() ? { name: projectName.trim() } : undefined,
        }),
      });
      if (!response.ok) {
        setError(await readError(response));
        return;
      }
      setResult((await response.json()) as RunResponse);
    } catch (caught) {
      setError(`分析失败：${caught instanceof Error ? caught.message : String(caught)}`);
    } finally {
      setBusy(null);
    }
  }

  const payload = result?.payload;
  const byLevel = payload?.summary?.by_risk_level ?? {};
  const maxLevelCount = Math.max(1, ...Object.values(byLevel));

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
          <section className="wb-card">
            <div className="wb-card-head">
              <span className="wb-step">1</span>
              <h2>工程条件</h2>
            </div>
            <p className="wb-hint">
              判定必须知道基坑安全等级、支护形式与设计深度 H。<strong>留空 H 不会放宽判据</strong> ——
              含 %H 的累计值判据会转为弃权并进入人工复核队列。
            </p>
            <div className="wb-row">
              <Field label="安全等级">
                <select
                  value={safetyLevel}
                  onChange={(event) => setSafetyLevel(event.target.value as "一级" | "二级" | "三级")}
                >
                  <option value="一级">一级</option>
                  <option value="二级">二级</option>
                  <option value="三级">三级</option>
                </select>
              </Field>
              <Field label="支护形式">
                <select value={supportType} onChange={(event) => setSupportType(event.target.value)}>
                  <option value="地下连续墙">地下连续墙</option>
                  <option value="灌注桩">灌注桩</option>
                  <option value="钢板桩">钢板桩</option>
                  <option value="型钢水泥土墙">型钢水泥土墙</option>
                  <option value="土钉墙">土钉墙</option>
                </select>
              </Field>
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
            <div className="wb-row">
              <Field label="工程名称（可选）">
                <input value={projectName} onChange={(event) => setProjectName(event.target.value)} />
              </Field>
              <Field label="报告日期">
                <input
                  type="date"
                  value={reportDate}
                  onChange={(event) => setReportDate(event.target.value)}
                />
              </Field>
            </div>
            {!depthValid && <p className="wb-hint">基坑设计深度需为 0~200 之间的数字。</p>}
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
            <div className="wb-drop">
              <input
                id="wb-file"
                type="file"
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

          <section className="wb-card">
            <div className="wb-card-head">
              <span className="wb-step">3</span>
              <h2>用户规范（可选）</h2>
            </div>
            <p className="wb-hint">
              不上传时使用默认规范库，<strong>不作任何特殊处理</strong>。上传后按字段级覆盖默认值，
              系统会逐项比较严格程度，凡是<strong>比默认更宽松</strong>的都会列出差异与默认值的规范条文依据。
            </p>
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
                disabled={busy === "standard" || !standardText.trim()}
              >
                {busy === "standard" ? (
                  <Loader2 size={14} aria-hidden="true" />
                ) : (
                  <Upload size={14} aria-hidden="true" />
                )}
                上传并校验
              </button>
              {standard && (
                <button
                  className="wb-btn wb-btn-sm"
                  type="button"
                  onClick={() => {
                    setStandard(null);
                    reset();
                  }}
                >
                  移除（改用默认库）
                </button>
              )}
            </div>

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

          <section className="wb-card">
            <div className="wb-card-head">
              <span className="wb-step">4</span>
              <h2>运行分析</h2>
            </div>
            <p className="wb-hint">
              阶段一 数据准备 → 阶段二 确定性计算 → 阶段三 规范比对。
              输出为结构化载荷，<strong>不生成日报正文</strong>。
            </p>
            <div className="wb-actions">
              <button
                className="wb-btn wb-btn-primary"
                type="button"
                onClick={() => void runAnalysis()}
                disabled={busy !== null || !monitoring}
              >
                {busy === "run" ? (
                  <Loader2 size={15} aria-hidden="true" />
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
                    setStandardText("");
                    reset();
                  }}
                >
                  清空
                </button>
              )}
            </div>
          </section>
        </div>

        {/* ---------------- 右列：结果 ---------------- */}
        <div className="wb-col">
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
