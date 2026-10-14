import "server-only";
import { createHash, randomUUID } from "node:crypto";
import { rm } from "node:fs/promises";
import { resolve } from "node:path";
import { z } from "zod";
import {
  artifactFactBindingSchema,
  artifactEnvelopeSchema,
  citationBindingSchema,
  factBindingSchema,
  reportArtifactSchema,
  reportDraftSchema,
  supportingSnapshotSchema,
  type ArtifactEnvelope,
  type ReportDraft,
  type SupportingSnapshot,
} from "@/contracts/agent-runtime";
import { callSkillScript } from "@/server/skills/python-bridge";

const rendererResultSchema = z.strictObject({
  report_payload: z.unknown(),
  fact_bindings: z.array(factBindingSchema),
  artifacts: z.array(reportArtifactSchema).length(3),
  artifact_bindings: z.array(artifactFactBindingSchema),
  citations: z.array(citationBindingSchema),
  template_version: z.string().trim().min(1),
  review_required: z.literal(true),
});

type RenderDailyReportRequest = {
  engineSnapshot: ArtifactEnvelope;
  evidenceSnapshot?: SupportingSnapshot | null;
  analysisSnapshot?: SupportingSnapshot | null;
  templateVersion?: string;
  version?: number;
};

export type RenderDailyReportResult = {
  draft: ReportDraft;
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

function parseSupportingSnapshot(
  snapshot: SupportingSnapshot | null | undefined,
): SupportingSnapshot | null {
  return snapshot ? supportingSnapshotSchema.parse(snapshot) : null;
}

function supportingPayload(snapshot: SupportingSnapshot | null): unknown {
  return snapshot?.status === "ready"
    ? (snapshot.artifact?.payload ?? null)
    : null;
}

export async function renderDailyReport(
  request: RenderDailyReportRequest,
): Promise<RenderDailyReportResult> {
  const engineSnapshot = artifactEnvelopeSchema.parse(request.engineSnapshot);
  if (
    engineSnapshot.ref.schema !== "excavaguard.daily_report_input/v1" ||
    (engineSnapshot.payload as { schema?: unknown })?.schema !==
      "excavaguard.daily_report_input/v1"
  ) {
    throw new Error("报告渲染只接受 excavaguard.daily_report_input/v1 引擎快照。");
  }

  const evidenceSnapshot = parseSupportingSnapshot(request.evidenceSnapshot);
  const analysisSnapshot = parseSupportingSnapshot(request.analysisSnapshot);
  const version = z.number().int().positive().parse(request.version ?? 1);
  const templateVersion = z
    .string()
    .trim()
    .min(1)
    .parse(request.templateVersion ?? "deep-pit-monitoring-report/service-v2");
  const artifactId = randomUUID();
  const artifactOutputDir = resolve(
    process.cwd(),
    "var",
    "report-artifacts",
    artifactId,
  );

  try {
    const envelope = await callSkillScript(
      "render-daily-report",
      "render_daily_report.py",
      {
        daily_report_input: engineSnapshot.payload,
        standard_evidence: supportingPayload(evidenceSnapshot),
        work_condition_analysis: supportingPayload(analysisSnapshot),
        template_version: templateVersion,
        artifact_id: artifactId,
        artifact_output_dir: artifactOutputDir,
      },
    );
    const result = rendererResultSchema.parse(envelope.result);
    const sourceRefs = {
      engine: engineSnapshot.ref,
      evidence: evidenceSnapshot?.artifact?.ref ?? null,
      analysis: analysisSnapshot?.artifact?.ref ?? null,
    };
    const draft = reportDraftSchema.parse({
      ref: {
        artifact_id: artifactId,
        schema: "excavaguard.report_draft/v1",
        version,
        content_hash: contentHash({
          source_refs: sourceRefs,
          report_payload: result.report_payload,
          fact_bindings: result.fact_bindings,
          artifacts: result.artifacts,
          artifact_bindings: result.artifact_bindings,
          citations: result.citations,
          review_required: true,
        }),
      },
      source_refs: sourceRefs,
      fact_bindings: result.fact_bindings,
      artifacts: result.artifacts,
      artifact_bindings: result.artifact_bindings,
      citations: result.citations,
      review_required: true,
      payload: result.report_payload,
    });

    return {
      draft,
      trace: {
        ...(envelope.trace ?? {}),
        template_version: result.template_version,
      },
    };
  } catch (error) {
    await rm(artifactOutputDir, { recursive: true, force: true });
    throw error;
  }
}
