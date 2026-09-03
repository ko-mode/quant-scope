/**
 * Minimal fetch wrapper for the QuantScope API.
 *
 * Typed endpoint functions live in `./securities`; React Query hooks in
 * `./hooks`. This module only owns the base URL, the error type, and JSON
 * transport. Works in both server components and the browser.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number, options?: ErrorOptions) {
    super(message, options);
    this.name = "ApiError";
    this.status = status;
  }
}

/** True for a 404 from the API - "no such resource", not a transport failure. */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { accept: "application/json", ...init?.headers },
    });
  } catch (cause) {
    throw new ApiError(`GET ${path} failed: network error`, 0, { cause });
  }

  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body?.detail === "string") detail = ` - ${body.detail}`;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(`GET ${path} failed with ${response.status}${detail}`, response.status);
  }

  return (await response.json()) as T;
}
