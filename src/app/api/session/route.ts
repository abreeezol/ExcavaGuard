import { z } from "zod";
import { accessStatus, loginCookie, logoutCookie } from "@/server/access";
import { apiError, apiErrorFromException, apiOk } from "@/server/api/respond";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET(request: Request) {
  try {
    return apiOk(accessStatus(request));
  } catch (error) {
    return apiErrorFromException(error);
  }
}

export async function POST(request: Request) {
  try {
    if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json") {
      return apiError(415, "UNSUPPORTED_MEDIA_TYPE", "请使用 application/json。");
    }
    const parsed = z.strictObject({ password: z.string().min(1).max(1024), username: z.string().trim().max(80).optional() })
      .safeParse(await request.json().catch(() => null));
    if (!parsed.success) return apiError(400, "INVALID_REQUEST", "请输入访问密码。");
    const response = apiOk({ authenticated: true });
    response.headers.set("Set-Cookie", loginCookie(request, parsed.data.password, parsed.data.username));
    return response;
  } catch (error) {
    return apiErrorFromException(error);
  }
}

export function DELETE(request: Request) {
  try {
    const response = apiOk({ authenticated: false });
    response.headers.set("Set-Cookie", logoutCookie(request));
    return response;
  } catch (error) {
    return apiErrorFromException(error);
  }
}
