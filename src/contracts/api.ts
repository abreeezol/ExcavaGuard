import { z } from "zod";

export const apiErrorSchema = z.strictObject({
  error: z.strictObject({
    code: z.enum([
      // --- 协议层 ---
      "UNSUPPORTED_MEDIA_TYPE",
      "INVALID_JSON",
      "INVALID_REQUEST",
      "FEATURE_NOT_IMPLEMENTED",
      // --- 文件层 ---
      "UNSUPPORTED_FILE_TYPE",
      "FILE_TOO_LARGE",
      "FILE_EMPTY",
      "FILE_NOT_FOUND",
      "FILE_UNREADABLE",
      // --- 数据与规范层（由引擎回传） ---
      "MISSING_FIELD",
      "DATA_QUALITY",
      "INVALID_STANDARD",
      // --- 引擎层 ---
      "ENGINE_NOT_FOUND",
      "ENGINE_UNAVAILABLE",
      "ENGINE_ERROR",
      "STORAGE_ERROR",
    ]),
    message: z.string(),
    fields: z.array(z.string()).optional(),
    /** 引擎返回的原始错误码，便于排查（不包含任何密钥）。 */
    engine_code: z.string().optional(),
  }),
});

export type ApiError = z.infer<typeof apiErrorSchema>;
export type ApiErrorCode = ApiError["error"]["code"];
