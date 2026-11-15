// The terminal is a client of the public API and nothing else. Every call goes through this file.

export const API = "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

type Query = Record<string, string | number | boolean | undefined | null | (string | number)[]>;

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((item) => params.append(key, String(item)));
    else params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

async function request<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
  const response = await fetch(API + withQuery(path, query), {
    method,
    credentials: "same-origin",
    headers: {
      "X-Aurex-Client": "terminal-web",
      ...(body !== undefined && !(body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
    },
    body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let payload: unknown = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const error = (payload as { error?: { code?: string; message?: string; details?: Record<string, unknown> } })
      ?.error;
    throw new ApiError(
      response.status,
      error?.code ?? "http_error",
      error?.message ?? `Request failed (${response.status})`,
      error?.details ?? {},
    );
  }
  return payload as T;
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>("GET", path, undefined, query),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body ?? {}),
  delete: <T>(path: string) => request<T>("DELETE", path),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, form),
};

/** A short sentence for the user. Plan and license refusals say what to do next. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "entitlement_denied") {
      const limit = error.details.limit as string | undefined;
      return limit
        ? `Your plan's limit for ${limit.replaceAll("_", " ")} is reached. Upgrade the plan to add more.`
        : "This feature is not part of your current plan.";
    }
    if (error.code === "license_denied") return "The data license does not permit this use.";
    if (error.code === "quota_exceeded") return "Today's plan allowance is used up. It resets at 00:00 UTC.";
    if (error.code === "rate_limited") return "Too many requests. Try again in a moment.";
    if (error.code === "validation_failed") {
      const issues = error.details.issues as { field: string; problem: string }[] | undefined;
      if (issues?.length) return `${issues[0].field || "Input"}: ${issues[0].problem}`;
    }
    return error.message;
  }
  return "The server could not be reached. Check the connection and try again.";
}
