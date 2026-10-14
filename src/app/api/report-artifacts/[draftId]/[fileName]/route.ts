import { readFile } from "node:fs/promises";
import { isAbsolute, relative, resolve } from "node:path";
import { z } from "zod";
import { apiError } from "@/server/api/respond";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const paramsSchema = z.strictObject({
  draftId: z.uuid(),
  fileName: z
    .string()
    .trim()
    .regex(
      /^监测日报_(?:\d{4}-\d{2}-\d{2}|date-pending)_草稿(?:_封面|_附表及清单)?\.(?:xlsx|md)$/,
    ),
});

export async function GET(
  _request: Request,
  context: { params: Promise<{ draftId: string; fileName: string }> },
) {
  const parsed = paramsSchema.safeParse(await context.params);
  if (!parsed.success) {
    return apiError(400, "INVALID_REQUEST", "报告产物路径不合法。");
  }

  const root = resolve(process.cwd(), "var", "report-artifacts");
  const draftRoot = resolve(root, parsed.data.draftId);
  const filePath = resolve(draftRoot, parsed.data.fileName);
  const draftRelative = relative(root, draftRoot);
  const fileRelative = relative(draftRoot, filePath);
  if (
    draftRelative.startsWith("..") ||
    isAbsolute(draftRelative) ||
    fileRelative.startsWith("..") ||
    isAbsolute(fileRelative)
  ) {
    return apiError(400, "INVALID_REQUEST", "报告产物路径越界。");
  }

  let content: Buffer;
  try {
    content = await readFile(filePath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException)?.code === "ENOENT") {
      return apiError(404, "FILE_NOT_FOUND", "报告产物不存在或已清理。");
    }
    return apiError(500, "STORAGE_ERROR", "读取报告产物失败。");
  }

  const mediaType = parsed.data.fileName.endsWith(".xlsx")
    ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    : "text/markdown; charset=utf-8";
  return new Response(new Uint8Array(content), {
    status: 200,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": mediaType,
      "Content-Length": String(content.byteLength),
      "Content-Disposition":
        `attachment; filename*=UTF-8''${encodeURIComponent(parsed.data.fileName)}`,
      "X-Content-Type-Options": "nosniff",
    },
  });
}
