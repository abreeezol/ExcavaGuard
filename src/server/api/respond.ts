import "server-only";
import type { ApiError, ApiErrorCode } from "@/contracts/api";
import { EngineError, EngineUnavailableError } from "@/server/skills/python-bridge";
import { StorageError } from "@/server/storage/monitoring-file-store";

/** 统一的 API 错误响应。所有响应都不缓存。 */
export function apiError(
  status: number,
  code: ApiErrorCode,
  message: string,
  extra?: { fields?: string[]; engine_code?: string },
): Response {
  return Response.json({ error: { code, message, ...extra } } satisfies ApiError, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

export function apiOk(body: unknown, status = 200): Response {
  return Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
}

const ENGINE_CODE_MAP: Record<string, { status: number; code: ApiErrorCode }> = {
  INVALID_INPUT: { status: 400, code: "INVALID_REQUEST" },
  MISSING_FIELD: { status: 422, code: "MISSING_FIELD" },
  DATA_QUALITY: { status: 422, code: "DATA_QUALITY" },
  FILE_NOT_FOUND: { status: 404, code: "FILE_NOT_FOUND" },
  FILE_UNREADABLE: { status: 422, code: "FILE_UNREADABLE" },
  INVALID_STANDARD: { status: 400, code: "INVALID_STANDARD" },
  ENGINE_NOT_FOUND: { status: 500, code: "ENGINE_NOT_FOUND" },
  ENGINE_ERROR: { status: 500, code: "ENGINE_ERROR" },
};

const STORAGE_STATUS: Record<StorageError["code"], number> = {
  UNSUPPORTED_FILE_TYPE: 415,
  FILE_TOO_LARGE: 413,
  FILE_EMPTY: 400,
  FILE_NOT_FOUND: 404,
  STORAGE_ERROR: 500,
};

/**
 * 把内部异常映射为 API 错误响应。
 * 引擎错误码原样放进 `engine_code`，便于排查，且**不含任何密钥或文件内容**。
 */
export function apiErrorFromException(error: unknown): Response {
  if (error instanceof StorageError) {
    return apiError(STORAGE_STATUS[error.code], error.code, error.message);
  }
  if (error instanceof EngineError) {
    const mapped = ENGINE_CODE_MAP[error.engineCode] ?? { status: 500, code: "ENGINE_ERROR" as const };
    return apiError(mapped.status, mapped.code, error.message, { engine_code: error.engineCode });
  }
  if (error instanceof EngineUnavailableError) {
    return apiError(503, "ENGINE_UNAVAILABLE", error.message);
  }
  return apiError(
    500,
    "ENGINE_ERROR",
    `未预期错误：${error instanceof Error ? error.message : String(error)}`,
  );
}
