import { resumeRequestSchema } from "@/contracts/runs";
import { requireProjectAction } from "@/server/access";
import { apiError, apiErrorFromException, apiOk } from "@/server/api/respond";
import { resumeRun, runView } from "@/server/runs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request, context: { params: Promise<{ runId: string }> }) {
  try {
    const access = requireProjectAction(request, "write");
    if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json") {
      return apiError(415, "UNSUPPORTED_MEDIA_TYPE", "请使用 application/json。");
    }
    const input = resumeRequestSchema.safeParse(await request.json().catch(() => null));
    if (!input.success) return apiError(400, "INVALID_REQUEST", "请提交当前运行修订号。");
    const { runId } = await context.params;
    return apiOk(runView(await resumeRun(runId, input.data.expected_revision, access)));
  } catch (error) {
    return apiErrorFromException(error);
  }
}
