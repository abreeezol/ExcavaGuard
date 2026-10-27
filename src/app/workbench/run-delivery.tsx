"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import type { PersistedRun, ReviewRequest } from "@/contracts/runs";
import { evidenceReferences, evidenceSourceLocation, standardCitation, standardName, type StandardCoverage } from "@/contracts/evidence-display";
import { standardEvidenceSchema } from "@/contracts/standard-evidence";

const DECISIONS = { accepted: "接受草稿", needs_changes: "退回修改", rejected: "拒绝草稿" } as const;
const AGENTS = { supervisor: "Supervisor", "report-delivery": "报告交付 Agent", audit: "审计 Agent" };
const STATUS: Record<string, string> = {
  ready_for_report: "待生成报告", draft_ready: "待审计", revision_required: "待报告修订",
  awaiting_human_review: "待工程师复核", stopped: "已停止自动处理",
  running: "执行中", completed: "执行已结束", waiting: "等待能力恢复", failed: "执行失败",
};

export function executionLabel(value: string): string {
  return STATUS[value] ?? value;
}

export function decisionLabel(value: ReviewRequest["decision"]): string {
  return DECISIONS[value];
}

export function RunDelivery({
  record, disabled, onReview, onResume, onDownload, onLoadInputs, canReviewRole = true, canWrite = true,
}: {
  record: PersistedRun;
  canReviewRole?: boolean;
  canWrite?: boolean;
  disabled: boolean;
  onReview: (decision: ReviewRequest["decision"], reason: string) => void;
  onResume: () => void;
  onDownload: (url: string, fileName: string) => void;
  onLoadInputs: () => void;
}) {
  const [reason, setReason] = useState("");
  const execution = record.result?.agent_run;
  const state = execution?.state;
  const models = [...new Set(state?.trace.filter((event) =>
    event.capability.startsWith("llm-") && event.status === "success",
  ).map((event) => event.output_versions.model).filter(Boolean) ?? [])];
  const evidencePayload = state?.evidence_snapshot?.artifact?.payload;
  const extendedReview = evidencePayload && typeof evidencePayload === "object" && "extended_review" in evidencePayload
    ? evidencePayload.extended_review as { status?: string; notice?: string; checks?: Array<{ group: string; additional_evidence_ids: string[] }> } : null;
  const coverage = evidencePayload && typeof evidencePayload === "object" && "coverage" in evidencePayload
    ? evidencePayload.coverage as StandardCoverage : null;
  const candidates = evidencePayload && typeof evidencePayload === "object" && "evidence" in evidencePayload
    && Array.isArray(evidencePayload.evidence) ? evidencePayload.evidence : [];
  const evidence = candidates.flatMap((candidate) => {
    const parsed = standardEvidenceSchema.safeParse(candidate);
    return parsed.success ? [parsed.data] : [];
  });
  const reportPayload = state?.report_draft?.payload;
  const markdown = reportPayload && typeof reportPayload === "object" && "markdown" in reportPayload
    && typeof reportPayload.markdown === "string" ? reportPayload.markdown : null;
  const canReview = canReviewRole && record.execution_status === "completed" &&
    state?.run.status === "awaiting_human_review" && state.audit_result?.valid &&
    !record.review && state.human_review.decision === null;

  return (
    <section className="wb-card" aria-label="报告交付与运行轨迹">
      <div className="wb-card-head"><h2>报告交付与运行轨迹</h2></div>
      <div className="wb-meta">
        <span className="wb-chip">运行 {record.run_id.slice(0, 8)} · 修订 {record.revision}</span>
        <span className="wb-chip">{executionLabel(record.execution_status)}</span>
        {state && <span className="wb-chip">{record.review ? decisionLabel(record.review.decision) : executionLabel(state.run.status)}</span>}
        {state && <span className="wb-chip">自动修订 {state.run.revision_count}/{state.limits.max_revision_rounds}</span>}
        {state && <span className="wb-chip">{state.report_mode === "ai" ? "AI 报告" : "确定性模板"} · 模型调用 {state.limits.model_calls_used}/{state.limits.max_model_calls}</span>}
        {models.map((model) => <span className="wb-chip" key={model}>{model}</span>)}
      </div>
      {record.error && <div className="wb-alert wb-alert-error" role="alert">{record.error.code}：{record.error.message}</div>}
      <div className="wb-actions">
        <button className="wb-btn wb-btn-sm" disabled={disabled} onClick={onLoadInputs}>加载输入并新建关联运行</button>
        {canWrite && state && record.execution_status !== "completed" && !record.review && (
          <button className="wb-btn wb-btn-sm" disabled={disabled} onClick={onResume}>从检查点续跑</button>
        )}
      </div>
      {!state && <p className="wb-hint">本次运行未生成报告。可加载输入并勾选报告生成后重新运行。</p>}
      {execution && (
        <>
          <p className="wb-hint">{execution.terminal_action.details}</p>
          {state?.audit_result && (
            <p className="wb-hint">独立一致性审计：{state.audit_result.valid ? "通过" : "未通过"}。所有报告仍为草稿，需工程师复核。</p>
          )}
          <div className="wb-actions">
            {execution.downloads.map((artifact) => (
              <button className="wb-btn wb-btn-sm" disabled={disabled}
                key={artifact.kind} onClick={() => onDownload(artifact.url, artifact.file_name)}>
                <Download size={14} aria-hidden="true" />
                {artifact.kind === "workbook" ? "下载 Excel" : artifact.kind === "cover_markdown" ? "下载封面" : "下载附表及清单"}
              </button>
            ))}
          </div>
          {state?.audit_result?.issues.map((issue) => (
            <p className="wb-hint" key={issue.issue_id}>{issue.code} · {issue.responsibility}：{issue.message}</p>
          ))}
          {markdown && (
            <details className="wb-accordion">
              <summary>监测报告正文预览{state?.audit_result?.valid ? "（审计通过，待工程师复核）" : "（未通过审计）"}</summary>
              <pre style={{ whiteSpace: "pre-wrap" }}>{markdown}</pre>
            </details>
          )}
          {state?.evidence_snapshot && (
            <details className="wb-accordion">
              <summary>本次 RAG 规范依据 · {evidence.length} 条</summary>
              {coverage && <details className="wb-accordion">
                <summary>规范目录覆盖 · 已查询 {coverage.queried_count}/{coverage.catalogue_count} 本</summary>
                <p>{coverage.notice}</p>
                <p>相关候选 {coverage.candidate_count} 条 · 保留 {coverage.retained_count} 条 · 预算截断 {coverage.omitted_count} 条</p>
                {coverage.standards.map(entry => <p key={entry.standard_version}>《{standardName(entry.standard_name)}》 {entry.standard_version}：{entry.reason}</p>)}
              </details>}
              {extendedReview && <div className="wb-alert wb-alert-info"><div>
                <strong>多日预警追加规范核查</strong>
                <p>{extendedReview.status === "additional_candidates" ? "检索到补充条文候选，须工程师确认适用性。" : "未检索到额外证据，不代表没有新要求，须人工继续查证。"}</p>
                <p>{extendedReview.notice}</p>
                {extendedReview.checks?.map((check) => <p key={check.group}>{check.group} · 新增候选 {check.additional_evidence_ids.length} 条</p>)}
              </div></div>}
              {state.evidence_snapshot.gaps.map((gap) => <p className="wb-hint" key={gap}>{gap}</p>)}
              {evidence.map((item) => (
                <div key={item.id}>
                  <p>{standardCitation(item.metadata)}</p>
                  <p className="wb-hint">{item.provider} · {evidenceSourceLocation(item.metadata.source_location)}</p>
                  <pre style={{ whiteSpace: "pre-wrap" }}>{item.text}</pre>
                </div>
              ))}
            </details>
          )}
          {state?.trace.map((event, index) => (
            <details className="wb-accordion" key={event.event_id}>
              <summary>{index + 1}. {AGENTS[event.agent]} · {event.capability} · {event.status}</summary>
              <p className="wb-hint">{event.started_at} → {event.finished_at}</p>
              {event.return_reason && <p>{event.return_reason}</p>}
              {event.error && <p role="alert">{event.error.code}：{event.error.message}</p>}
              <p className="wb-hint">规则：{event.rule_ids.join("、") || "无"}；证据：{evidenceReferences(event.evidence_ids, evidence) || "无"}</p>
              <pre>{JSON.stringify({ 输入版本: event.input_versions, 输出版本: event.output_versions }, null, 2)}</pre>
            </details>
          ))}
        </>
      )}
      {record.review && (
        <div className="wb-alert wb-alert-info" role="status">
          <div>
            {decisionLabel(record.review.decision)} · {record.review.submitted_at}
            <p>{record.review.reason}</p>
            <p>已记录当前草稿的复核决定。正式预警、审核与签发仍由工程师负责。</p>
          </div>
        </div>
      )}
      {canReview && (
        <fieldset className="wb-review" disabled={disabled}>
          <legend>工程师复核</legend>
          <p className="wb-hint">确认对象为当前已审计草稿。退回后请修正输入并建立关联运行；原报告与理由保留。</p>
          <label className="wb-field">
            <span>复核理由（必填）</span>
            <textarea maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} />
          </label>
          <div className="wb-actions">
            {(Object.keys(DECISIONS) as ReviewRequest["decision"][]).map((decision) => (
              <button className="wb-btn wb-btn-sm" key={decision} disabled={disabled || !reason.trim()}
                onClick={() => onReview(decision, reason.trim())}>{DECISIONS[decision]}</button>
            ))}
          </div>
        </fieldset>
      )}
    </section>
  );
}
