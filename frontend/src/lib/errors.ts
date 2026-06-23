"use client";

import { toast } from "sonner";

import { ApiError } from "./api";

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/**
 * Surface an ``ApiError`` as a user-facing toast. Non-``ApiError`` values fall
 * back to a generic message. The caller can still branch on the returned
 * status for side effects (redirect on 401, inline highlight on 413, …).
 */
export function toastApiError(error: unknown, fallback = "Something went wrong."): number | null {
  if (!isApiError(error)) {
    toast.error(fallback);
    return null;
  }
  const suffix = error.requestId ? ` (id: ${error.requestId})` : "";
  switch (error.status) {
    case 401:
      toast.error("Your session has expired. Please log in again.");
      break;
    case 413:
      toast.error(error.detail || "File is too large.");
      break;
    case 429:
      toast.error("Too many requests. Please wait a moment and try again.");
      break;
    default:
      if (error.status >= 500) {
        toast.error(`Server error${suffix}. Please try again later.`);
      } else {
        toast.error(`${error.detail}${suffix}`);
      }
  }
  return error.status;
}
