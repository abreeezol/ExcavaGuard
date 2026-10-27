import { z } from "zod";
import { requireIdentity } from "@/server/access";
import { createAuthorizedProject } from "@/server/auth/directory";
import { apiError, apiErrorFromException, apiOk } from "@/server/api/respond";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export function GET(request: Request) {
  try { const status = requireIdentity(request); return apiOk({ projects: status.projects, project_id: status.project_id, can_create_project: status.can_create_project }); }
  catch (error) { return apiErrorFromException(error); }
}
export async function POST(request: Request) {
  try {
    const status = requireIdentity(request);
    if (!status.can_create_project) return apiError(403, "FORBIDDEN", "当前账号无权新建工程。");
    const parsed = z.strictObject({ name: z.string().trim().min(1).max(100) }).safeParse(await request.json().catch(() => null));
    if (!parsed.success) return apiError(400, "INVALID_REQUEST", "请填写工程名称（最多100字符）。");
    return apiOk({ project: await createAuthorizedProject(status.user!.id, parsed.data.name) }, 201);
  } catch (error) { return apiErrorFromException(error); }
}
