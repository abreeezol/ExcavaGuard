import "server-only";

export type EvidenceRetrievalErrorCode =
  | "INVALID_QUERY"
  | "RETRIEVER_NOT_CONFIGURED"
  | "RETRIEVER_UNAVAILABLE"
  | "INVALID_RESPONSE"
  | "QUERY_FAILED";

export class EvidenceRetrievalError extends Error {
  constructor(
    readonly code: EvidenceRetrievalErrorCode,
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "EvidenceRetrievalError";
  }
}
