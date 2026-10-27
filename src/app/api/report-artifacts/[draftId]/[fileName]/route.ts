import { z } from "zod";
import { apiError, apiErrorFromException } from "@/server/api/respond";
import { requireAccess } from "@/server/access";
import { readRunByDraftId } from "@/server/storage/run-store";
import { readReportFile } from "@/server/storage/report-files";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const paramsSchema = z.strictObject({
  draftId: z.uuid(),
  fileName: z
    .string()
    .trim()
    .regex(
      /^(?:监测日报_(?:\d{4}-\d{2}-\d{2}|date-pending)|监测(?:周报|月报|区间报告)_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2})_草稿(?:_封面|_附表及清单)?\.(?:xlsx|md)$/,
    ),
});

export async function GET(
  request: Request,
  context: { params: Promise<{ draftId: string; fileName: string }> },
) {
  const parsed = paramsSchema.safeParse(await context.params);
  if (!parsed.success) {
    return apiError(400, "INVALID_REQUEST", "报告产物路径不合法。");
  }

  try {
    const access = requireAccess(request);
    const record = await readRunByDraftId(parsed.data.draftId, access);
    const allowed = record &&
      record.execution_status === "completed" &&
      record.result?.agent_run?.state.report_draft?.ref.artifact_id === parsed.data.draftId &&
      record.result.agent_run.state.audit_result?.valid === true &&
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
