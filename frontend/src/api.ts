/** A failed response is distinct from a write whose outcome is unknown. */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly outcomeUnknown = false,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function errorDetail(value: unknown): string | undefined {
  if (!value || typeof value !== "object" || !("detail" in value)) return;
  const detail = value.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item: unknown) =>
      item &&
      typeof item === "object" &&
      "msg" in item &&
      typeof item.msg === "string"
        ? [item.msg]
        : [],
    );
    return messages.length ? messages.join("; ") : undefined;
  }
}

/** One request only: writes must be reconciled by their durable server intent. */
export async function requestJson<T>(
  path: string,
  options: RequestInit = {},
  timeoutMs = 30_000,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort(options.signal?.reason);
  if (options.signal?.aborted) abort();
  else options.signal?.addEventListener("abort", abort, { once: true });
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const isWrite = options.method !== undefined && options.method !== "GET";
  try {
    const response = await fetch(path, {
      ...options,
      signal: controller.signal,
      cache: "no-store",
    });
    const result: unknown = await response.json().catch((cause: unknown) => {
      if (controller.signal.aborted) throw cause;
      return undefined;
    });
    if (!response.ok) {
      throw new ApiError(
        isWrite && response.status >= 500
          ? `${errorDetail(result) || "The API is unavailable."} Check the activity ledger before repeating this action.`
          : errorDetail(result) || "The API is unavailable. Please retry.",
        response.status,
        isWrite && response.status >= 500,
      );
    }
    if (result === undefined) {
      throw new ApiError(
        isWrite
          ? "The server returned an unreadable response. Check the activity ledger before repeating this action."
          : "The server returned an unreadable response. Please retry.",
        response.status,
        isWrite,
      );
    }
    return result as T;
  } catch (cause) {
    if (cause instanceof ApiError) throw cause;
    // Navigation cancellation remains silent in the polling hook.
    if (options.signal?.aborted) throw cause;
    throw new ApiError(
      isWrite
        ? "The action could not be confirmed. Check the activity ledger before repeating it."
        : timedOut
          ? "The request timed out. Please retry when the connection returns."
          : "Unable to connect. Please retry when the connection returns.",
      undefined,
      isWrite,
    );
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", abort);
  }
}

export async function api<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  return requestJson<T>(
    `/api/${path}`,
    body !== undefined
      ? {
          signal,
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Cognition-Intent": "session",
          },
          body: JSON.stringify(body),
        }
      : { signal },
  );
}
