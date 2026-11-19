import "server-only";
import { createHash, randomUUID } from "node:crypto";
import type { ArtifactEnvelope } from "@/contracts/agent-runtime";
import type { PersistedRun } from "@/contracts/runs";
import type { ReportNarrative } from "@/contracts/ai-report";

export type RevisionFeedback = {
  schema: "excavaguard.engineer_feedback/v1";
  parent_run_id: string;
  parent_revision: number;
  parent_draft_ref: unknown;
  prior_narrative: unknown;
  items: Array<{ feedback_id: string; comment: string; target?: unknown }>;
};

export function freezeEngineerFeedback(parent: PersistedRun): ArtifactEnvelope | undefined {
  if (parent.review?.decision !== "needs_changes") {
    // An unresolved child may be rerun with corrected inputs before a new review.
    return !parent.review && parent.revision_feedback ? structuredClone(parent.revision_feedback) : undefined;
  }
  const draft = parent.result?.agent_run?.state.report_draft;
  const payload: RevisionFeedback = {
    schema: "excavaguard.engineer_feedback/v1", parent_run_id: parent.run_id,
    parent_revision: parent.revision, parent_draft_ref: parent.review.draft_ref,
    prior_narrative: (draft?.payload as { sections?: { narrative?: unknown } })?.sections?.narrative ?? null,
    items: [
      { feedback_id: "review", comment: parent.review.reason },
      ...parent.review.evaluations.map((evaluation, index) => ({
        feedback_id: `risk-${index}`, comment: evaluation.comment, target: evaluation,
      })),
    ],
  };
  return { ref: { artifact_id: randomUUID(), schema: payload.schema, version: 1,
    content_hash: createHash("sha256").update(JSON.stringify(payload)).digest("hex") }, payload };
}

export function validateFeedbackResponses(narrative: ReportNarrative, feedback?: ArtifactEnvelope) {
  const expected = ((feedback?.payload as RevisionFeedback | undefined)?.items ?? []).map(item => item.feedback_id);
  const actual = (narrative.feedback_responses ?? []).map(item => item.feedback_id);
  if (new Set(actual).size !== actual.length || JSON.stringify([...expected].sort()) !== JSON.stringify([...actual].sort())) {
    throw new Error(`FEEDBACK_RESPONSE_REQUIRED：本次允许且必须回应的ID为${JSON.stringify(expected.slice(0,10))}，收到${JSON.stringify(actual.slice(0,10))}；无工程师意见时须省略或返回空数组，previous_issues不属于工程师意见。`);
  }
}
