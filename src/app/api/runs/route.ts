import type { ApiError } from "@/contracts/api";
import { createRunRequestSchema } from "@/contracts/runs";

export const runtime = "nodejs";

function rejectRequest(status: number, error: ApiError["error"]) {
  return Response.json(
    { error } satisfies ApiError,
    { status, headers: { "Cache-Control": "no-store" } },
  );
}

export async function POST(request: Request) {
  const mediaType = request.headers.get("content-type")?.split(";")[0].trim().toLowerCase();
  if (mediaType !== "application/json") {
    return rejectRequest(415, {
      code: "UNSUPPORTED_MEDIA_TYPE",
      message: "请使用 application/json。",
    });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return rejectRequest(400, {
      code: "INVALID_JSON",
      message: "请求正文不是有效 JSON。",
    });
  }

  const parsed = createRunRequestSchema.safeParse(body);
  if (!parsed.success) {
    return rejectRequest(400, {
      code: "INVALID_REQUEST",
      message: "请检查项目、监测文件标识和报告日期。",
      fields: [...new Set(parsed.error.issues.map((issue) => issue.path.join(".")))],
    });
  }

  // 鉴权、资源授权、持久化及 Supervisor 接通前，禁止接受任何分析任务。
  return rejectRequest(501, {
    code: "FEATURE_NOT_IMPLEMENTED",
    message: "分析链路尚未接入，未创建运行记录或报告。",
  });
}
