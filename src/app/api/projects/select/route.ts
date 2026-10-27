import { z } from "zod";
import { requireIdentity, selectProjectCookie } from "@/server/access";
import { apiError, apiErrorFromException, apiOk } from "@/server/api/respond";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function POST(request: Request) {
  try {
    requireIdentity(request);
    const parsed = z.strictObject({ project_id: z.uuid() }).safeParse(await request.json().catch(() => null));
    if (!parsed.success) return apiError(400, "INVALID_REQUEST", "请选择合法工程。");
    const session = selectProjectCookie(request, parsed.data.project_id);
    const response = apiOk({ project_id: parsed.data.project_id });
    response.headers.set("Set-Cookie", session);
    return response;
  } catch (error) { return apiErrorFromException(error); }
}
