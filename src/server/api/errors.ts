import "server-only";
import type { ApiErrorCode } from "@/contracts/api";

export class AppError extends Error {
  constructor(
    readonly status: number,
    readonly code: ApiErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "AppError";
  }
}
