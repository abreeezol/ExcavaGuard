"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { PersistedRun, ReviewRequest } from "@/contracts/runs";
import {
  engineerEvaluationDispositionSchema,
  knownRiskLevelSchema,
  riskEvaluationTargets,
  riskReviewTargets,
  type EngineerEvaluationDisposition,
  type EngineerRiskEvaluationInput,
  type KnownRiskLevel,
} from "@/contracts/engineer-evaluation";
import { isAuditComplete } from "@/contracts/audit-status";

const DECISIONS = {
  accepted: "接受草稿",
  needs_changes: "退回修改",
  rejected: "拒绝草稿",
} as const;

const EVALUATION_DISPOSITIONS: Record<EngineerEvaluationDisposition, string> = {
  confirmed: "确认风险结论",
  follow_up_required: "确认并持续跟踪",
  disputed: "对风险结论有异议",
};

export function EngineerReviewPanel({
  record,
  disabled,
  canReviewRole,
  onReview,
  onSaveEvaluations,
  onDirtyChange,
}: {
  record: PersistedRun;
  disabled: boolean;
  canReviewRole: boolean;
  onReview: (
    decision: ReviewRequest["decision"],
    reason: string,
    evaluations: EngineerRiskEvaluationInput[],
  ) => void;
  onSaveEvaluations: (evaluations: EngineerRiskEvaluationInput[], reason: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [reason, setReason] = useState(record.evaluation_draft?.reason ?? "");
  const [riskEvaluations, setRiskEvaluations] = useState<Record<number, {
    disposition: EngineerEvaluationDisposition | "";
    comment: string;
    reviewedRiskLevel: KnownRiskLevel | "";
  }>>(() => Object.fromEntries((record.evaluation_draft?.evaluations ?? []).map(item =>
    [item.risk_item_index, {
      disposition: item.disposition,
      comment: item.comment,
      reviewedRiskLevel: item.reviewed_risk_level ?? "",
    }],
  )));
  const [activeRiskPosition, setActiveRiskPosition] = useState(0);
  const state = record.result?.agent_run?.state;
  const reviewReady =
    record.execution_status === "completed" &&
    state?.run.status === "awaiting_human_review" &&
    isAuditComplete(state.audit_result, state.report_mode) &&
    !record.review &&
    state.human_review.decision === null;
  const reviewTargets = useMemo(
    () => riskReviewTargets(record.result?.payload),
    [record.result?.payload],
  );
  const requiredTargetIndexes = useMemo(
    () => new Set(riskEvaluationTargets(record.result?.payload).map(target => target.risk_item_index)),
    [record.result?.payload],
  );
  const evaluationInputs = useMemo<EngineerRiskEvaluationInput[]>(() => reviewTargets.flatMap(target => {
    const evaluation = riskEvaluations[target.risk_item_index];
    const comment = evaluation?.comment.trim() ?? "";
    if (!evaluation?.disposition ||
        !comment ||
        (target.risk_level === "未知" && !evaluation.reviewedRiskLevel)) {
      return [];
    }
    return [{
      risk_item_index: target.risk_item_index,
      disposition: evaluation.disposition,
      comment,
      ...(evaluation.reviewedRiskLevel
        ? { reviewed_risk_level: evaluation.reviewedRiskLevel }
        : {}),
    }];
  }), [reviewTargets, riskEvaluations]);
  const evaluationInputByIndex = useMemo(
    () => new Map(evaluationInputs.map(evaluation => [evaluation.risk_item_index, evaluation])),
    [evaluationInputs],
  );
  const hasPartialEvaluation = reviewTargets.some(target => {
    const evaluation = riskEvaluations[target.risk_item_index];
    const hasAnyValue = Boolean(
      evaluation?.disposition ||
      evaluation?.comment.trim() ||
      evaluation?.reviewedRiskLevel,
    );
    if (!hasAnyValue) return false;
    return !evaluation?.disposition ||
      !evaluation.comment.trim() ||
      (target.risk_level === "未知" && !evaluation.reviewedRiskLevel);
  });
  const completedRequiredCount = [...requiredTargetIndexes]
    .filter(index => evaluationInputByIndex.has(index)).length;
  const reviewedUnknownCount = reviewTargets
    .filter(target => target.risk_level === "未知" && evaluationInputByIndex.has(target.risk_item_index))
    .length;
  const unknownTargetCount = reviewTargets.filter(target => target.risk_level === "未知").length;
  const canAccept = completedRequiredCount === requiredTargetIndexes.size &&
    evaluationInputs.every(evaluation => evaluation.disposition !== "disputed");
  const activeRiskTarget = reviewTargets[activeRiskPosition];
  const activeRiskEvaluation = activeRiskTarget
    ? riskEvaluations[activeRiskTarget.risk_item_index] ?? {
      disposition: "",
      comment: "",
      reviewedRiskLevel: "",
    }
    : null;

  useEffect(() => {
    const saved = Object.fromEntries((record.evaluation_draft?.evaluations ?? []).map(item =>
      [item.risk_item_index, {
        disposition: item.disposition,
        comment: item.comment,
        reviewedRiskLevel: item.reviewed_risk_level ?? "",
      }],
    ));
    const changed = reason !== (record.evaluation_draft?.reason ?? "") ||
      Object.entries(riskEvaluations).some(([key, value]) => {
        const original = saved[key];
        return value.disposition !== (original?.disposition ?? "") ||
          value.comment !== (original?.comment ?? "") ||
          value.reviewedRiskLevel !== (original?.reviewedRiskLevel ?? "");
      });
    onDirtyChange(changed);
  }, [reason, riskEvaluations, record.evaluation_draft, onDirtyChange]);

  function updateRiskEvaluation(
    riskItemIndex: number,
    patch: Partial<{
      disposition: EngineerEvaluationDisposition | "";
      comment: string;
      reviewedRiskLevel: KnownRiskLevel | "";
    }>,
  ) {
    setRiskEvaluations(current => ({
      ...current,
      [riskItemIndex]: {
        disposition: current[riskItemIndex]?.disposition ?? "",
        comment: current[riskItemIndex]?.comment ?? "",
        reviewedRiskLevel: current[riskItemIndex]?.reviewedRiskLevel ?? "",
        ...patch,
      },
    }));
  }

  if (!canReviewRole) return null;

  if (!reviewReady) {
    let unavailableReason = "当前报告尚未进入待工程师复核状态。";
    if (record.review) {
      unavailableReason = "本次工程师复核已提交，已归档的评价和决定可在报告交付记录中查看。";
    } else if (record.execution_status !== "completed" || !state) {
      unavailableReason = "当前运行尚未完成报告交付；请先修复失败项并基于此报告重新分析。";
    } else if (!state.report_draft) {
      unavailableReason = "当前运行尚未形成报告草稿；请基于此报告重新分析后再复核。";
    } else if (!isAuditComplete(state.audit_result, state.report_mode)) {
      unavailableReason = "报告审查尚未通过，暂不能提交工程师复核；请先完成修订或重新分析。";
    }

    return <section className="wb-card wb-engineer-review" aria-label="工程师复核">
      <div className="wb-card-head">
        <span className="wb-step">审</span>
        <h2>工程师复核</h2>
      </div>
      <p className="wb-hint">{unavailableReason}</p>
    </section>;
  }

  return <section className="wb-card wb-engineer-review" aria-label="工程师复核">
    <div className="wb-card-head">
      <span className="wb-step">审</span>
      <h2>工程师复核</h2>
    </div>
    <fieldset className="wb-engineer-review-fields" disabled={disabled}>
      <p className="wb-hint">
        系统原判保持不变。关注及以上风险必须逐项评价；未知/弃权项可由工程师
        明确给出最终等级，未填写时仍保持待确定。
      </p>
      {reviewTargets.length > 0 ? <div className="wb-risk-evaluations">
        <h3>
          风险逐项评价 · 必评 {completedRequiredCount}/{requiredTargetIndexes.size}
          {unknownTargetCount > 0 && ` · 未知已判定 ${reviewedUnknownCount}/${unknownTargetCount}`}
        </h3>
        <div className="wb-risk-navigator">
          <label className="wb-field">
            <span>定位风险条目</span>
            <select
              value={activeRiskPosition}
              onChange={event => {
                const position = Number(event.target.value);
                if (Number.isInteger(position) && position >= 0 && position < reviewTargets.length) {
                  setActiveRiskPosition(position);
                }
              }}
            >
              {reviewTargets.map((target, position) => {
                const completed = evaluationInputByIndex.has(target.risk_item_index);
                return <option value={position} key={target.risk_item_index}>
                  {position + 1}/{reviewTargets.length} · {target.point_id ?? "未提供点号"} ·
                  {target.metric_name} · {target.risk_level} ·
                  {completed ? "已完成" : target.risk_level === "未知" ? "可选复核" : "待评价"}
                </option>;
              })}
            </select>
          </label>
          <div className="wb-risk-navigation">
            <button
              type="button"
              className="wb-btn wb-icon-btn"
              aria-label="上一条风险"
              title="上一条风险"
              disabled={activeRiskPosition === 0}
              onClick={() => setActiveRiskPosition(position => Math.max(0, position - 1))}
            >
              <ChevronLeft size={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="wb-btn wb-icon-btn"
              aria-label="下一条风险"
              title="下一条风险"
              disabled={activeRiskPosition === reviewTargets.length - 1}
              onClick={() => setActiveRiskPosition(position =>
                Math.min(reviewTargets.length - 1, position + 1)
              )}
            >
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </div>
        </div>
        {activeRiskTarget && activeRiskEvaluation && <div className="wb-risk-evaluation">
          <p>
            <strong>{activeRiskTarget.point_id ?? "未提供点号"} · {activeRiskTarget.metric_name}</strong>
            <span className="wb-chip">系统原判：{activeRiskTarget.risk_level}</span>
          </p>
          <p className="wb-hint">{activeRiskTarget.timestamp ?? "未提供观测时间"}</p>
          <label className="wb-field">
            <span>工程师最终等级</span>
            <select
              aria-label="工程师最终等级"
              value={activeRiskEvaluation.reviewedRiskLevel}
              onChange={event => {
                const value = event.target.value;
                if (value === "") {
                  updateRiskEvaluation(activeRiskTarget.risk_item_index, {
                    reviewedRiskLevel: "",
                  });
                  return;
                }
                const parsed = knownRiskLevelSchema.safeParse(value);
                if (parsed.success) updateRiskEvaluation(activeRiskTarget.risk_item_index, {
                  reviewedRiskLevel: parsed.data,
                });
              }}
            >
              <option value="">
                {activeRiskTarget.risk_level === "未知"
                  ? "保持待确定（不提交评价）"
                  : `保持系统原判（${activeRiskTarget.risk_level}）`}
              </option>
              {knownRiskLevelSchema.options
                .filter(level => level !== activeRiskTarget.risk_level)
                .map(level => <option value={level} key={level}>{level}</option>)}
            </select>
          </label>
          <label className="wb-field">
            <span>评价结论</span>
            <select
              aria-label="评价结论"
              value={activeRiskEvaluation.disposition}
              onChange={event => {
                const value = event.target.value;
                if (value === "") {
                  updateRiskEvaluation(activeRiskTarget.risk_item_index, { disposition: "" });
                  return;
                }
                const parsed = engineerEvaluationDispositionSchema.safeParse(value);
                if (parsed.success) updateRiskEvaluation(activeRiskTarget.risk_item_index, {
                  disposition: parsed.data,
                });
              }}
            >
              <option value="">请选择</option>
              {(Object.keys(EVALUATION_DISPOSITIONS) as EngineerEvaluationDisposition[]).map(value => (
                <option value={value} key={value}>{EVALUATION_DISPOSITIONS[value]}</option>
              ))}
            </select>
          </label>
          <label className="wb-field">
            <span>工程师说明</span>
            <textarea
              className="wb-evaluation-comment"
              maxLength={1000}
              value={activeRiskEvaluation.comment}
              onChange={event => updateRiskEvaluation(activeRiskTarget.risk_item_index, {
                comment: event.target.value,
              })}
            />
          </label>
        </div>}
      </div> : <p className="wb-hint">本次没有需要逐项评价或可选判定的风险。</p>}
      <label className="wb-field">
        <span>复核总评（必填）</span>
        <textarea
          className="wb-review-reason"
          maxLength={2000}
          value={reason}
          onChange={event => setReason(event.target.value)}
        />
      </label>
      {reviewTargets.length > 0 && <p className="wb-hint">
        接受草稿前须完成全部已知非正常风险；未知项可留空。存在“有异议”时请退回修改并建立关联运行。
      </p>}
      <div className="wb-actions">
        <button
          className="wb-btn wb-btn-sm"
          disabled={disabled || !evaluationInputs.length || hasPartialEvaluation}
          onClick={() => onSaveEvaluations(evaluationInputs, reason.trim())}
        >
          暂存风险评价
        </button>
        {(Object.keys(DECISIONS) as ReviewRequest["decision"][]).map(decision => (
          <button
            className={`wb-btn wb-btn-sm${decision === "accepted" ? " wb-btn-primary" : ""}`}
            key={decision}
            disabled={
              disabled || !reason.trim() || hasPartialEvaluation ||
              (decision === "accepted" && !canAccept)
            }
            onClick={() => onReview(decision, reason.trim(), evaluationInputs)}
          >
            {DECISIONS[decision]}
          </button>
        ))}
      </div>
    </fieldset>
  </section>;
}
