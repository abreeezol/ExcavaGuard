"use client";

import { PreparationSummary } from "./preparation-summary";
import { auditStages, isAuditComplete, AUDIT_STAGE_LABELS } from "@/contracts/audit-status";
import { Download } from "lucide-react";
import type { PersistedRun, ReviewRequest } from "@/contracts/runs";
import {
  type EngineerEvaluationDisposition,
} from "@/contracts/engineer-evaluation";
import { evidenceReferences, evidenceSourceLocation, standardCitation, standardName, type StandardCoverage } from "@/contracts/evidence-display";
import { standardEvidenceSchema } from "@/contracts/standard-evidence";

const DECISIONS = { accepted: "接受草稿", needs_changes: "退回修改", rejected: "拒绝草稿" } as const;
const EVALUATION_DISPOSITIONS: Record<EngineerEvaluationDisposition, string> = {
  confirmed: "确认风险结论",
  follow_up_required: "确认并持续跟踪",
  disputed: "对风险结论有异议",
};
const AGENTS = { supervisor: "Supervisor", "report-delivery": "报告交付 Agent", audit: "审计 Agent" };
const STATUS: Record<string, string> = {
  ready_for_report: "待生成报告", draft_ready: "待审计", revision_required: "待报告修订",
  awaiting_human_review: "待工程师复核", stopped: "已停止自动处理",
  running: "执行中", completed: "执行已结束", waiting: "等待能力恢复", failed: "执行失败",
};
const RISK_LEVELS = ["正常", "关注", "预警", "报警", "危险报警", "未知"] as const;

export function executionLabel(value: string): string {
  return STATUS[value] ?? value;
}

export function decisionLabel(value: ReviewRequest["decision"]): string {
  return DECISIONS[value];
}

export function RunDelivery({
  record, disabled, onResume, onDownload, onLoadInputs, canWrite = true,
}: {
  record: PersistedRun;
  canWrite?: boolean;
  disabled: boolean;
  onResume: () => void;
  onDownload: (url: string, fileName: string) => void;
  onLoadInputs: () => void;
}) {
  const execution = record.result?.agent_run;
  const state = execution?.state;
  const models = [...new Set(state?.trace.filter((event) =>
    event.capability.startsWith("llm-") && event.status === "success",
  ).map((event) => event.output_versions.model).filter(Boolean) ?? [])];
  const evidencePayload = state?.evidence_snapshot?.artifact?.payload;
  const extendedReview = evidencePayload && typeof evidencePayload === "object" && "extended_review" in evidencePayload
    ? evidencePayload.extended_review as { status?: string; notice?: string; checks?: Array<{ group: string; additional_evidence_ids: string[] }> } : null;
  const investigationReview=evidencePayload&&typeof evidencePayload==='object'&&'supervisor_investigations'in evidencePayload?evidencePayload.supervisor_investigations as {checks?:Array<{question:string;rationale:string;additional_evidence_ids:string[];status:string}>}:null;
  const coverage = evidencePayload && typeof evidencePayload === "object" && "coverage" in evidencePayload
    ? evidencePayload.coverage as StandardCoverage : null;
  const candidates = evidencePayload && typeof evidencePayload === "object" && "evidence" in evidencePayload
    && Array.isArray(evidencePayload.evidence) ? evidencePayload.evidence : [];
  const evidence = candidates.flatMap((candidate) => {
    const parsed = standardEvidenceSchema.safeParse(candidate);
    return parsed.success ? [parsed.data] : [];
  });
  const reportPayload = state?.report_draft?.payload;
  const feedbackItems=((record.revision_feedback?.payload??state?.revision_feedback?.payload) as {items?:Array<{feedback_id:string;comment:string}>}|undefined)?.items??[];
  const feedbackResponses=reportPayload&&typeof reportPayload==='object'&&'sections'in reportPayload?(reportPayload.sections as {narrative?:{feedback_responses?:Array<{feedback_id:string;status:string;response:{text:string;evidence_ids:string[]}}>}})?.narrative?.feedback_responses??[]:[];
  const markdown = reportPayload && typeof reportPayload === "object" && "markdown" in reportPayload
    && typeof reportPayload.markdown === "string" ? reportPayload.markdown : null;
  const auditComplete = isAuditComplete(state?.audit_result, state?.report_mode);
  const stages = auditStages(state?.audit_result, state?.report_mode);
  const savedEvaluations = new Map(
    record.evaluation_draft?.evaluations.map(item => [item.risk_item_index, item]) ?? [],
  );
  const effectiveSummary = record.review?.effective_summary;
  const payloadSummary = record.result?.payload && typeof record.result.payload === "object" &&
    "summary" in record.result.payload
    ? (record.result.payload as {
      summary?: { by_risk_level?: Record<string, number>; overall_risk_level?: string };
    }).summary
    : null;

  return (
    <section className="wb-card" aria-label="报告交付与运行轨迹">
      <div className="wb-card-head"><h2>报告交付与运行轨迹</h2></div>
      <div className="wb-meta">
        <span className="wb-chip">运行 {record.run_id.slice(0, 8)} · 修订 {record.revision}</span>
        <span className="wb-chip">{executionLabel(record.execution_status)}</span>
        {state && <span className="wb-chip">{record.review ? decisionLabel(record.review.decision) : state.audit_result && !auditComplete ? "审查未通过或未完成" : executionLabel(state.run.status)}</span>}
        {state && <span className="wb-chip">自动修订 {state.run.revision_count}/{state.limits.max_revision_rounds}</span>}
        {state && <span className="wb-chip">{state.report_mode === "ai" ? "AI 报告" : "确定性模板"} · 模型调用 {state.limits.model_calls_used}/{state.limits.max_model_calls}</span>}
        {models.map((model) => <span className="wb-chip" key={model}>{model}</span>)}
      </div>
      <p className="wb-hint">生成者：{record.created_by?.name ?? "历史记录未保存姓名"} · {record.created_at}</p>
      {record.source_files && <details className="wb-accordion">
        <summary>本报告输入文件 · {record.source_files.length} 份</summary>
        {record.source_files.map(file => <p key={file.file_id}>
          {file.original_name} · 上传者：{file.uploaded_by?.name ?? "历史记录未保存上传者"} · {file.created_at}
        </p>)}
      </details>}
      <PreparationSummary payload={record.result?.payload} />
      {record.revision_feedback && <p className="wb-hint">本稿已载入工程师退回意见，请核对下方逐项回应与报告正文。未解决事项须人工确认，不能直接接受草稿。</p>}
      {record.error && <div className="wb-alert wb-alert-error" role="alert">{record.error.code}：{record.error.message}</div>}
      <div className="wb-actions">
        {canWrite && <button className="wb-btn wb-btn-sm" disabled={disabled} onClick={onLoadInputs}>{record.review?.decision === "needs_changes" || (!record.review && record.revision_feedback) ? "载入输入并按退回意见重编" : "基于此报告重新分析"}</button>}
        {canWrite && state && record.execution_status !== "completed" && !record.review && (
          <button className="wb-btn wb-btn-sm" disabled={disabled} onClick={onResume}>从检查点续跑</button>
        )}
      </div>
      {!state && <p className="wb-hint">本次运行未生成报告。可加载输入并勾选报告生成后重新运行。</p>}
      {execution && (
        <>
          <p className="wb-hint">{state?.audit_result && !auditComplete && execution.terminal_action.reason_code === "AUDIT_PASSED" ? "历史记录的语义审查未完成，需重新运行并完成审查。" : execution.terminal_action.details}</p>
          {state?.report_draft && (
            <p className="wb-hint">文件校验：{AUDIT_STAGE_LABELS[stages.deterministic]}；语义审查：{AUDIT_STAGE_LABELS[stages.semantic]}。{auditComplete ? "本模式所需审查已通过，仍需工程师复核。" : "完整审查尚未通过，仅保留草稿供排查。"}</p>
          )}
          <div className="wb-actions">
            {(auditComplete ? execution.downloads : []).map((artifact) => (
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
              <summary>监测报告正文预览{auditComplete ? "（本模式审查通过，待工程师复核）" : "（审查未通过或未完成，仅供排查）"}</summary>
              <pre style={{ whiteSpace: "pre-wrap" }}>{markdown}</pre>
            </details>
          )}
          {!!feedbackResponses.length&&<details className="wb-accordion"><summary>报告Agent · 工程师意见逐项回应</summary>{feedbackResponses.map(response=><div key={response.feedback_id}><strong>{response.status==='addressed'?'已回应修改要求':'需工程师确认'}</strong><p>原意见：{feedbackItems.find(item=>item.feedback_id===response.feedback_id)?.comment??'本次冻结的工程师意见'}</p><p>回应：{response.response.text}</p><p className="wb-hint">依据：{evidenceReferences(response.response.evidence_ids,evidence)||'冻结事实或已提供资料'}；回应完成不代表现场事实已核实。</p></div>)}</details>}
          {!!investigationReview?.checks?.length&&<details className="wb-accordion"><summary>Supervisor · 定向查证 {investigationReview.checks.length} 项</summary>{investigationReview.checks.map((check,index)=><div key={index}><strong>{check.question}</strong><p>目的：{check.rationale}</p><p>{check.additional_evidence_ids.length?`新增候选 ${check.additional_evidence_ids.length} 条`:'未增加新候选，不代表不存在相关要求。'}</p><p className="wb-hint">{evidenceReferences(check.additional_evidence_ids,evidence)}</p></div>)}</details>}
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
          {state?.audit_result && !auditComplete && <p className="wb-hint">当前审查未通过，以下保留原始轨迹用于追溯，不作为通过依据。</p>}
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
            <p className="wb-hint">复核人：{record.review.submitted_by?.name ?? record.review.owner_id}</p>
            <p>{record.review.reason}</p>
            {effectiveSummary && <div className="wb-evaluation-results">
              <strong>工程师复核后汇总 · 调整 {effectiveSummary.adjusted_count} 条</strong>
              <p>
                总体等级 {payloadSummary?.overall_risk_level ?? "未知"} →
                {effectiveSummary.overall_risk_level}
              </p>
              <div className="wb-meta">
                {RISK_LEVELS.map(level => <span className="wb-chip" key={level}>
                  {level} {payloadSummary?.by_risk_level?.[level] ?? 0} →
                  {effectiveSummary.by_risk_level[level]}
                </span>)}
              </div>
            </div>}
            {record.review.evaluations.length > 0 && (
              <div className="wb-evaluation-results">
                <strong>已提交风险评价 {record.review.evaluations.length} 条</strong>
                {record.review.evaluations.map((evaluation) => (
                  <p key={evaluation.risk_item_index}>
                    {evaluation.point_id ?? "未提供点号"} · {evaluation.metric_name} ·
                    系统原判 {evaluation.risk_level} → 工程师最终
                    {evaluation.reviewed_risk_level ?? evaluation.risk_level}
                    {!evaluation.reviewed_risk_level && "（保持原判）"} ·
                    {EVALUATION_DISPOSITIONS[evaluation.disposition]}：
                    {evaluation.comment}
                    {savedEvaluations.get(evaluation.risk_item_index) && (
                      <>（填写人：{savedEvaluations.get(evaluation.risk_item_index)?.evaluated_by.name} ·
                        {savedEvaluations.get(evaluation.risk_item_index)?.evaluated_at}）</>
                    )}
                  </p>
                ))}
              </div>
            )}
            <p>已记录当前草稿的复核决定。正式预警、审核与签发仍由工程师负责。</p>
          </div>
        </div>
      )}
      {record.evaluation_draft && !record.review && <details className="wb-accordion">
        <summary>共享暂存评价 · {record.evaluation_draft.evaluations.length} 条</summary>
        <p className="wb-hint">最后保存：{record.evaluation_draft.updated_by.name} · {record.evaluation_draft.updated_at}</p>
        {record.evaluation_draft.evaluations.map(item => <p key={item.risk_item_index}>
          {item.point_id ?? "未提供点号"} · {item.metric_name} ·
          系统原判 {item.risk_level} → 工程师最终 {item.reviewed_risk_level ?? item.risk_level}
          {!item.reviewed_risk_level && "（保持原判）"} · {EVALUATION_DISPOSITIONS[item.disposition]}：
          {item.comment}（{item.evaluated_by.name} · {item.evaluated_at}）
        </p>)}
        {record.evaluation_draft.reason && <p>暂存总评：{record.evaluation_draft.reason}</p>}
      </details>}
    </section>
  );
}
