import { saveEvaluationRequestSchema } from "@/contracts/runs";
import { requireProjectAction } from "@/server/access";
import { apiError, apiErrorFromException, apiOk } from "@/server/api/respond";
import { runView, saveRiskEvaluations } from "@/server/runs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request, context: { params: Promise<{ runId: string }> }) {
  try {
    const access = requireProjectAction(request, "review");
    if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") {
      return apiError(415, "UNSUPPORTED_MEDIA_TYPE", "请使用 application/json。");
    }
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return apiError(400, "INVALID_JSON", "请求正文不是有效 JSON。");
    }
    const parsed = saveEvaluationRequestSchema.safeParse(body);
    if (!parsed.success) {
      return apiError(400, "INVALID_REQUEST", "请提供当前修订号、草稿版本及完整的风险评价条目。");
    }
    const { runId } = await context.params;
    return apiOk(runView(await saveRiskEvaluations(runId, parsed.data, access)));
  } catch (error) {
    return apiErrorFromException(error);
  }
}
