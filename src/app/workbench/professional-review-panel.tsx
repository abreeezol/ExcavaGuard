"use client";

import { useEffect, useState } from "react";
import { ChevronRight, Download } from "lucide-react";
import {
  professionalReviewDecisionSchema,
  professionalReviewResponseSchema,
  professionalReviewSaveResponseSchema,
  type ProfessionalReviewData,
  type ProfessionalReviewDecision,
} from "@/contracts/professional-review";

const STATUS_LABELS: Record<string, string> = {
  pending_engineer_review: "待工程师复核",
  engineer_review_recorded: "已记录复核",
  needs_changes: "需修改",
};

function isAbort(error: unknown) {
  const text = error instanceof Error ? `${error.name} ${error.message}` : String(error);
  return /(?:signal is )?aborted|aborterror/i.test(text);
}

export function ProfessionalReviewPanel({
  apiFetch,
  canReview,
}: {
  apiFetch: (url: string, init?: RequestInit) => Promise<Response>;
  canReview: boolean;
}) {
  const [data, setData] = useState<ProfessionalReviewData | null>(null);
  const [decisions, setDecisions] = useState<Record<string, ProfessionalReviewDecision | "">>({});
  const [comments, setComments] = useState<Record<string, string>>({});
  const [source, setSource] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let stopped = false;
    void apiFetch("/api/professional-review")
      .then(async response => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.error?.message || "复核样例读取失败");
        return professionalReviewResponseSchema.parse(body);
      })
      .then(body => {
        if (stopped) return;
        setData(body);
        setSource(body.review?.source_reference ?? "");
        setDecisions(Object.fromEntries(
          body.review?.evaluations?.map(item => [item.case_id, item.decision]) ?? [],
        ));
        setComments(Object.fromEntries(
          body.review?.evaluations?.map(item => [item.case_id, item.comment]) ?? [],
        ));
      })
      .catch(error => {
        if (!stopped && !isAbort(error)) {
          setMessage(error instanceof Error ? error.message : "复核样例读取失败");
        }
      });
    return () => {
      stopped = true;
    };
  }, [apiFetch]);

  async function save() {
    if (!data || pending) return;
    setPending(true);
    setMessage("");
    try {
      const response = await apiFetch("/api/professional-review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          suite_hash: data.suite_hash,
          adapter_digest: data.adapter_digest,
          expected_revision: data.review?.revision ?? 0,
          source_reference: source,
          evaluations: data.suite.cases.map(item => ({
            case_id: item.case_id,
            decision: decisions[item.case_id],
            comment: comments[item.case_id] ?? "",
          })),
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error?.message || "保存失败");
      const saved = professionalReviewSaveResponseSchema.parse(body).review;
      setData(current => current ? {
        ...current,
        review: saved,
        status: saved.status,
      } : current);
      setMessage("复核记录已保存。");
    } catch (error) {
      if (!isAbort(error)) setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setPending(false);
    }
  }

  const status = data ? STATUS_LABELS[data.status] ?? data.status : "正在加载";
  const complete = Boolean(
    data &&
    source.trim() &&
    data.suite.cases.every(item => decisions[item.case_id]),
  );

  return <details className="wb-card wb-professional-review" aria-label="复核样例校验">
    <summary className="wb-professional-summary">
      <ChevronRight className="wb-professional-chevron" size={18} aria-hidden="true" />
      <span>
        <strong>复核样例校验</strong>
        <small>项目级规则与报告表达校验</small>
      </span>
      <span className="wb-chip">{status}</span>
    </summary>
    <div className="wb-professional-content">
      <div className="wb-actions">
        <a className="wb-btn wb-btn-sm" href="/api/professional-review?fixtures=1" download>
          <Download size={14} aria-hidden="true" />
          输入与预期样例
        </a>
        <a className="wb-btn wb-btn-sm" href="/api/professional-review?results=1" download>
          <Download size={14} aria-hidden="true" />
          软件重放结果
        </a>
      </div>
      <p className="wb-hint">这是项目级能力校验，不替代上方当前报告的工程师复核。</p>
      {data?.suite.cases.map(item => <section className="wb-review-sample" key={item.case_id}>
        <h3>{item.scenario}</h3>
        <p>{item.expected}</p>
        <div className="wb-row">
          <label className="wb-field">
            <span>评价结论</span>
            <select
              aria-label={item.scenario}
              disabled={!canReview || pending}
              value={decisions[item.case_id] ?? ""}
              onChange={event => {
                const value = event.target.value;
                const parsed = value === "" ? "" : professionalReviewDecisionSchema.safeParse(value);
                if (parsed === "" || parsed.success) {
                  setDecisions(current => ({
                    ...current,
                    [item.case_id]: parsed === "" ? "" : parsed.data,
                  }));
                }
              }}
            >
              <option value="">请选择评价</option>
              <option value="pass">通过复核</option>
              <option value="needs_changes">需修改</option>
            </select>
          </label>
          <label className="wb-field">
            <span>问题或复核说明</span>
            <input
              disabled={!canReview || pending}
              value={comments[item.case_id] ?? ""}
              onChange={event => setComments(current => ({
                ...current,
                [item.case_id]: event.target.value,
              }))}
            />
          </label>
        </div>
      </section>)}
      <label className="wb-field">
        <span>复核依据</span>
        <input
          placeholder="例如：批准方案、手算记录"
          value={source}
          disabled={!canReview || pending}
          onChange={event => setSource(event.target.value)}
        />
      </label>
      <div className="wb-actions">
        <button
          className="wb-btn wb-btn-primary"
          type="button"
          disabled={!canReview || pending || !complete}
          onClick={() => void save()}
        >
          {pending ? "正在保存…" : "保存复核样例记录"}
        </button>
      </div>
      {message && <p role="status" className="wb-hint">{message}</p>}
    </div>
  </details>;
}
