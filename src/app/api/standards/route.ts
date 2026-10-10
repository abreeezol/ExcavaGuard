import { apiError, apiErrorFromException, apiOk } from "@/server/api/respond";
import { userStandardPayloadSchema } from "@/contracts/monitoring-files";
import { checkStandardStrictness } from "@/server/skills/evaluate-thresholds/runner";
import { listFiles, saveFile } from "@/server/storage/monitoring-file-store";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type StrictnessContext = {
  safety_level: "一级" | "二级" | "三级";
  support_type: string;
  excavation_depth_m: number | null;
};

const DEFAULT_CONTEXT: StrictnessContext = {
  safety_level: "一级",
  support_type: "any",
  excavation_depth_m: null,
};

/** 列出已上传的用户规范文件（新→旧）。 */
export async function GET() {
  return apiOk({ files: await listFiles("standard") });
}

function parseContext(raw: unknown): StrictnessContext {
  if (!raw) return DEFAULT_CONTEXT;
  const parsed = typeof raw === "string" ? safeJson(raw) : raw;
  if (!parsed || typeof parsed !== "object") return DEFAULT_CONTEXT;
  const record = parsed as Record<string, unknown>;
  const level = record.safety_level;
  const depth = record.excavation_depth_m;
  return {
    safety_level: level === "一级" || level === "二级" || level === "三级" ? level : "一级",
    support_type: typeof record.support_type === "string" && record.support_type.trim()
      ? record.support_type.trim()
      : "any",
    excavation_depth_m:
      typeof depth === "number" && Number.isFinite(depth) && depth > 0 ? depth : null,
  };
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/**
 * 上传用户规范（阈值）文件。
 *
 * 支持两种请求体：
 *   - `application/json`：`{ payload: {...}, context?: {...} }`
 *   - `multipart/form-data`：`file`（JSON 文件）+ 可选 `context`（JSON 字符串）
 *
 * **上传即校验严格程度**：与默认规范库逐字段比较，凡"比默认更宽松"的项
 * 连同默认值的规范名称与条文号一并返回（`report` 字段可直接展示）。
 * 更宽松可能是合法的地方规程，系统**只反馈不阻断**，但必须让用户看见。
 */
export async function POST(request: Request) {
  const mediaType = request.headers.get("content-type")?.split(";")[0].trim().toLowerCase();

  let rawPayload: unknown;
  let contextRaw: unknown;

  if (mediaType === "application/json") {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return apiError(400, "INVALID_JSON", "请求正文不是有效 JSON。");
    }
    if (!body || typeof body !== "object") {
      return apiError(400, "INVALID_REQUEST", "请求体必须是对象。");
    }
    const record = body as Record<string, unknown>;
    rawPayload = record.payload ?? body;
    contextRaw = record.context;
  } else if (mediaType === "multipart/form-data") {
    let form: FormData;
    try {
      form = await request.formData();
    } catch {
      return apiError(400, "INVALID_REQUEST", "无法解析 multipart 表单。");
    }
    contextRaw = form.get("context");
    const file = form.get("file");
    if (file instanceof File) {
      rawPayload = safeJson(await file.text());
    } else {
      rawPayload = safeJson(String(form.get("payload") ?? ""));
    }
  } else {
    return apiError(
      415,
      "UNSUPPORTED_MEDIA_TYPE",
      "请使用 application/json 或 multipart/form-data。",
    );
  }

  const parsed = userStandardPayloadSchema.safeParse(rawPayload);
  if (!parsed.success) {
    return apiError(400, "INVALID_STANDARD", "用户规范结构不合法。", {
      fields: [...new Set(parsed.error.issues.map((issue) => issue.path.join(".")))],
    });
  }

  const payload = parsed.data as Record<string, unknown>;
  const context = parseContext(contextRaw);

  try {
    // 先校验再落盘：结构非法或引擎拒绝时不留下垃圾文件
    const { strictness, report, problems } = await checkStandardStrictness(payload, context);
    if (problems.length > 0) {
      return apiError(400, "INVALID_STANDARD", problems.join("；"));
    }

    const sourceId = String(payload.source_id ?? "user_standard");
    const bytes = new TextEncoder().encode(JSON.stringify(payload, null, 2));
    const stored = await saveFile({
      kind: "standard",
      originalName: `${sourceId}.json`,
      bytes,
      mediaType: "application/json",
    });

    return apiOk({ file: stored, strictness, report }, 201);
  } catch (error) {
    return apiErrorFromException(error);
  }
}
