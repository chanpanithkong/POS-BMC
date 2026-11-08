import type { ApiErrorBody, ApiFieldError } from "@/types";

/** Client-side representation of the standard API error envelope (SRS 13.1). */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details: ApiFieldError[] = [],
    public readonly correlationId: string = "",
  ) {
    super(message);
    this.name = "ApiError";
  }

  static fromBody(status: number, body: ApiErrorBody): ApiError {
    const { code, message, details, correlation_id: correlationId } = body.error;
    return new ApiError(status, code, message, details ?? [], correlationId);
  }

  get isApprovalRequired() {
    return this.code === "APPROVAL_REQUIRED";
  }

  get isAuthError() {
    return this.status === 401;
  }
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}
