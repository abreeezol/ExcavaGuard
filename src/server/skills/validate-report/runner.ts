import "server-only";
import { createHash, randomUUID } from "node:crypto";
import { z } from "zod";
import {
  artifactEnvelopeSchema,
  auditResponsibilitySchema,
  auditResultSchema,
  reportDraftSchema,
  supportingSnapshotSchema,
  type ArtifactEnvelope,
  type ArtifactRef,
  type AuditResult,
  type ReportDraft,
  type SupportingSnapshot,
} from "@/contracts/agent-runtime";
import { callSkillScript } from "@/server/skills/python-bridge";

const auditCheckSchema = z.strictObject({
  name: z.string().trim().min(1),
  valid: z.boolean(),
  details: z.string().trim().min(1).optional(),
});

const scriptIssueSchema = z.strictObject({
  code: z.string().trim().min(1),
  severity: z.enum(["error", "warning"]),
  blocking: z.boolean(),
  responsibility: auditResponsibilitySchema,
  path: z.string().trim().min(1),
  message: z.string().trim().min(1),
  expected: z.unknown().optional(),
  actual: z.unknown().optional(),
});

const validatorResultSchema = z.strictObject({
  valid: z.boolean(),
  checks: z.array(auditCheckSchema),
  issues: z.array(scriptIssueSchema),
});

type ValidateReportRequest = {
  draft: ReportDraft;
  engineSnapshot: ArtifactEnvelope;
  evidenceSnapshot?: SupportingSnapshot | null;
  analysisSnapshot?: SupportingSnapshot | null;
  prohibitedPhrases?: string[];
  templateVersion?: string;
  version?: number;
};

export type ValidateReportResult = {
  audit: AuditResult;
  trace: Record<string, unknown>;
};

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, nested]) => [key, stableValue(nested)]),
    );
  }
  return value;
}

function contentHash(value: unknown): string {
  return createHash("sha256")
    .update(JSON.stringify(stableValue(value)))
    .digest("hex");
}

function sameRef(left: ArtifactRef | null, right: ArtifactRef | null): boolean {
  if (left === null || right === null) return left === right;
  return (
    left.artifact_id === right.artifact_id &&
    left.schema === right.schema &&
    left.version === right.version &&
    left.content_hash === right.content_hash
  );
}

function parseSupportingSnapshot(
  snapshot: SupportingSnapshot | null | undefined,
): SupportingSnapshot | null {
  return snapshot ? supportingSnapshotSchema.parse(snapshot) : null;
}

export async function validateReport(
  request: ValidateReportRequest,
): Promise<ValidateReportResult> {
  const draft = reportDraftSchema.parse(request.draft);
  const engineSnapshot = artifactEnvelopeSchema.parse(request.engineSnapshot);
  const evidenceSnapshot = parseSupportingSnapshot(request.evidenceSnapshot);
  const analysisSnapshot = parseSupportingSnapshot(request.analysisSnapshot);
  const version = z.number().int().positive().parse(request.version ?? 1);
  const templateVersion = z
    .string()
    .trim()
    .min(1)
    .parse(request.templateVersion ?? "deep-pit-monitoring-report/service-v3");

  if (!sameRef(draft.source_refs.engine, engineSnapshot.ref)) {
    throw new Error("报告草稿引用的引擎事实快照与审计输入不一致。");
  }
  if (
    !sameRef(
      draft.source_refs.evidence,
      evidenceSnapshot?.artifact?.ref ?? null,
    ) ||
    !sameRef(
      draft.source_refs.analysis,
      analysisSnapshot?.artifact?.ref ?? null,
    )
  ) {
    throw new Error("报告草稿引用的证据或分析快照与审计输入不一致。");
  }

  const envelope = await callSkillScript("validate-report", "validate_report.py", {
    daily_report_input: engineSnapshot.payload,
    report_payload: draft.payload,
    fact_bindings: draft.fact_bindings,
    artifacts: draft.artifacts,
    artifact_bindings: draft.artifact_bindings,
    citations: draft.citations,
    standard_evidence:
      evidenceSnapshot?.status === "ready" || evidenceSnapshot?.status === "insufficient"
        ? (evidenceSnapshot.artifact?.payload ?? null)
        : null,
    work_condition_analysis:
      analysisSnapshot?.status === "ready"
        ? (analysisSnapshot.artifact?.payload ?? null)
        : null,
    template_version: templateVersion,
    prohibited_phrases: request.prohibitedPhrases,
  });
  const result = validatorResultSchema.parse(envelope.result);
  const issues = result.issues.map((item, index) => ({
    issue_id: `audit-${version}-${index + 1}`,
    ...item,
  }));
  const audit = auditResultSchema.parse({
    ref: {
      artifact_id: randomUUID(),
      schema: "excavaguard.audit_result/v1",
      version,
      content_hash: contentHash({
        draft_ref: draft.ref,
        valid: result.valid,
        checks: result.checks,
        issues,
      }),
    },
    draft_ref: draft.ref,
    valid: result.valid,
    checks: result.checks,
    issues,
  });

  return {
    audit,
    trace: envelope.trace ?? {},
  };
}
