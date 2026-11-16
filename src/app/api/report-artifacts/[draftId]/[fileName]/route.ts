import { isAuditComplete } from "@/contracts/audit-status";
import { z } from "zod";
import { apiError, apiErrorFromException } from "@/server/api/respond";
import { requireAccess } from "@/server/access";
import { readRunByDraftId } from "@/server/storage/run-store";
import { readReportFile } from "@/server/storage/report-files";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export const reportArtifactParamsSchema = z.strictObject({
  draftId: z.uuid(),
  fileName: z
    .string()
    .trim()
    .min(1)
    .max(500)
    .regex(/^[^/\\\0]+$/),
});

export async function GET(
  request: Request,
  context: { params: Promise<{ draftId: string; fileName: string }> },
) {
  const parsed = reportArtifactParamsSchema.safeParse(await context.params);
  if (!parsed.success) {
    return apiError(400, "INVALID_REQUEST", "报告产物路径不合法。");
  }

  try {
    const access = requireAccess(request);
    const record = await readRunByDraftId(parsed.data.draftId, access);
    const allowed = record &&
      record.execution_status === "completed" &&
      record.result?.agent_run?.state.report_draft?.ref.artifact_id === parsed.data.draftId &&
      isAuditComplete(record.result.agent_run.state.audit_result, record.result.agent_run.state.report_mode) &&
      record.result.agent_run.state.run.status === "awaiting_human_review" &&
      record.review?.decision !== "needs_changes" && record.review?.decision !== "rejected";
    const artifact = allowed ? record.result?.agent_run?.state.report_draft?.artifacts
      .find((item) => item.file_name === parsed.data.fileName) : undefined;
    if (!artifact) return apiError(404, "FILE_NOT_FOUND", "未找到可下载的当前已审计草稿。");
    const content = await readReportFile(artifact);

    return new Response(new Uint8Array(content), {
      status: 200,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": artifact.media_type,
        "Content-Length": String(content.byteLength),
        "Content-Disposition":
          `attachment; filename*=UTF-8''${encodeURIComponent(parsed.data.fileName)}`,
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (error) {
    return apiErrorFromException(error);
  }
}
