import { z } from "zod";

export const apiErrorSchema = z.strictObject({
  error: z.strictObject({
    code: z.enum([
      "UNSUPPORTED_MEDIA_TYPE",
      "INVALID_JSON",
      "INVALID_REQUEST",
      "FEATURE_NOT_IMPLEMENTED",
    ]),
    message: z.string(),
    fields: z.array(z.string()).optional(),
  }),
});

export type ApiError = z.infer<typeof apiErrorSchema>;
