/**
 * Minimal fetch wrapper for the QuantScope API.
 *
 * Phase 0 provides only the base URL and error type. Typed endpoint functions
 * and React Query hooks are added in Phase 1, ideally generated from the API's
 * OpenAPI schema (see docs/architecture.md).
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });

  if (!response.ok) {
    throw new ApiError(`GET ${path} failed with ${response.status}`, response.status);
  }

  return (await response.json()) as T;
}
