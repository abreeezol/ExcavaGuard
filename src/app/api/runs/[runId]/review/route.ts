import { reviewRequestSchema } from "@/contracts/runs";
import { requireProjectAction } from "@/server/access";
import { apiError, apiErrorFromException, apiOk } from "@/server/api/respond";
import { reviewRun, runView } from "@/server/runs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request, context: { params: Promise<{ runId: string }> }) {
  try {
    const access = requireProjectAction(request, "review");
    if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json") {
      return apiError(415, "UNSUPPORTED_MEDIA_TYPE", "请使用 application/json。");
    }
    const input = reviewRequestSchema.safeParse(await request.json().catch(() => null));
    if (!input.success) return apiError(400, "INVALID_REQUEST", "请提交当前修订号、草稿版本、复核决定和理由。");
    const { runId } = await context.params;
    return apiOk(runView(await reviewRun(runId, input.data, access)));
  } catch (error) {
    return apiErrorFromException(error);
  }
}
