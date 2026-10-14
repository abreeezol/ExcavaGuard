import { apiError, apiErrorFromException, apiOk } from "@/server/api/respond";
import { createRunRequestSchema } from "@/contracts/runs";
import { requireAccess } from "@/server/access";
import { createRun, runView } from "@/server/runs";
import { listRuns } from "@/server/storage/run-store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    return apiOk({ runs: await listRuns(requireAccess(request)) });
  } catch (error) {
    return apiErrorFromException(error);
  }
}

/** 默认只分析；报告链显式开启。输入、结果、Agent 检查点和失败均落盘。 */
export async function POST(request: Request) {
  try {
    requireAccess(request);
  } catch (error) {
    return apiErrorFromException(error);
  }
  const mediaType = request.headers.get("content-type")?.split(";")[0].trim().toLowerCase();
  if (mediaType !== "application/json") {
    return apiError(415, "UNSUPPORTED_MEDIA_TYPE", "请使用 application/json。");
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return apiError(400, "INVALID_JSON", "请求正文不是有效 JSON。");
  }

  const parsed = createRunRequestSchema.safeParse(body);
  if (!parsed.success) {
    return apiError(400, "INVALID_REQUEST", "请检查监测文件标识、报告日期与工程条件。", {
      fields: [...new Set(parsed.error.issues.map((issue) => issue.path.join(".")))],
    });
  }

  try {
    const access = requireAccess(request, parsed.data.project_id);
    return apiOk(runView(await createRun(parsed.data, access)));
  } catch (error) {
    return apiErrorFromException(error);
  }
}
