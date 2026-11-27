import { ApiError } from "../api/client";

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "rate_limited" && error.retryAfterSeconds) {
      return `${error.message} Try again in ${error.retryAfterSeconds}s.`;
    }
    return error.message;
  }
  return "Something went wrong. Try again.";
}

// A failure after which we do NOT know whether the server applied the request:
// no answer at all, a 5xx, or a rate limit. Idempotent calls may be retried safely.
export function isUncertain(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 0 || error.status >= 500 || error.status === 429);
}
