import { z } from "zod";
import { requireAccess, requireProjectAction } from "@/server/access";
import { apiError, apiErrorFromException, apiOk } from "@/server/api/respond";
import { listProjectStandards, setProjectStandardActive, uploadProjectStandard } from "@/server/evidence/project-standard-library";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try { return apiOk({ documents: await listProjectStandards(requireAccess(request).project_id) }); }
  catch (error) { return apiErrorFromException(error); }
}
export async function POST(request: Request) {
  try {
    const access = requireProjectAction(request, "standards");
    if (!request.headers.get("content-type")?.startsWith("multipart/form-data")) return apiError(415, "UNSUPPORTED_MEDIA_TYPE", "请使用 multipart/form-data 上传规范。");
    if (Number(request.headers.get("content-length")) > 21 * 1024 * 1024) return apiError(413, "FILE_TOO_LARGE", "规范文件不能超过20MB。");
    const form = await request.formData().catch(() => null);
    if (!form) return apiError(400, "INVALID_REQUEST", "无法解析上传表单。");
    const file = form.get("file");
    if (!(file instanceof File)) return apiError(400, "INVALID_STANDARD", "请选择规范文件。");
    return apiOk({ document: await uploadProjectStandard(access.project_id, file, {
      standard_name: form.get("standard_name"), standard_version: form.get("standard_version"),
      region: form.get("region"), applicability: form.get("applicability"), confirmed: form.get("confirmed") === "true",
    }) }, 201);
  } catch (error) { return apiErrorFromException(error); }
}
export async function PATCH(request: Request) {
  try {
    const access = requireProjectAction(request, "standards");
    const body = z.strictObject({ document_id: z.uuid(), active: z.boolean() }).safeParse(await request.json().catch(() => null));
    if (!body.success) return apiError(400, "INVALID_REQUEST", "请指定规范及启用状态。");
    return apiOk({ document: await setProjectStandardActive(access.project_id, body.data.document_id, body.data.active) });
  } catch (error) { return apiErrorFromException(error); }
}
