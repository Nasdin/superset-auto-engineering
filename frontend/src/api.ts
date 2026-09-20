export async function api<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const res = await fetch(
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
  if (!res.ok) {
    const error = await res.json().catch(() => null);
    throw new Error(
      typeof error?.detail === "string"
        ? error.detail
        : Array.isArray(error?.detail)
          ? error.detail.map((d: { msg: string }) => d.msg).join("; ")
          : "The API is unavailable. Please retry.",
    );
  }
  return res.json();
}
