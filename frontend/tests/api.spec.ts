import { test, expect } from "@playwright/test";
import { api, ApiError, requestJson } from "../src/api";
import { safeUrl } from "../src/links";

test("API preserves falsy request bodies and cancellation signals", async () => {
  const original = globalThis.fetch;
  const controller = new AbortController();
  let options: RequestInit | undefined;
  globalThis.fetch = async (_, init) => {
    options = init;
    return new Response('{"saved":true}', { status: 200 });
  };
  try {
    expect(await api("example", false, controller.signal)).toEqual({
      saved: true,
    });
    expect(options?.body).toBe("false");
    expect(options?.method).toBe("POST");
    expect(options?.signal).toBeInstanceOf(AbortSignal);
    expect(options?.signal?.aborted).toBe(false);
  } finally {
    globalThis.fetch = original;
  }
});

test("API explains structured validation errors and unavailable responses", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () =>
      new Response('{"detail":[{"msg":"Title required"}]}', { status: 422 });
    await expect(api("example")).rejects.toThrow("Title required");
    globalThis.fetch = async () =>
      new Response("proxy failed", { status: 502 });
    await expect(api("example")).rejects.toThrow("API is unavailable");
  } finally {
    globalThis.fetch = original;
  }
});

test("evidence links reject executable and credential-bearing URLs", () => {
  for (const url of [
    "javascript:alert(1)",
    "http://example.com",
    "https://user:password@example.com",
    "/relative",
  ]) {
    expect(safeUrl(url)).toBeUndefined();
  }
  expect(safeUrl("https://github.com/Nasdin/superset/pull/2")).toBe(
    "https://github.com/Nasdin/superset/pull/2",
  );
});

test("hung requests time out without replaying writes", async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async (_, options) => {
    calls++;
    return new Promise((_, reject) => {
      options?.signal?.addEventListener(
        "abort",
        () => reject(new DOMException("Aborted", "AbortError")),
        { once: true },
      );
    });
  };
  try {
    await expect(requestJson("/api/live/jobs", {}, 10)).rejects.toThrow(
      "timed out",
    );
    const error = await requestJson(
      "/api/live/jobs",
      { method: "POST", body: "{}" },
      10,
    ).catch((error: unknown) => error);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ outcomeUnknown: true });
    expect((error as Error).message).toContain("before repeating");
    expect(calls).toBe(2);
  } finally {
    globalThis.fetch = original;
  }
});

test("caller cancellation reaches the transport and preserves its reason", async () => {
  const original = globalThis.fetch;
  const controller = new AbortController();
  const reason = new DOMException("Navigation changed", "AbortError");
  globalThis.fetch = async (_, options) =>
    new Promise((_, reject) => {
      options?.signal?.addEventListener(
        "abort",
        () => reject(options.signal?.reason),
        { once: true },
      );
    });
  try {
    const request = api("example", undefined, controller.signal);
    controller.abort(reason);
    await expect(request).rejects.toBe(reason);
  } finally {
    globalThis.fetch = original;
  }
});

test("malformed provider responses produce safe errors with unknown write outcome", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () =>
      new Response("<html>proxy error</html>", { status: 502 });
    await expect(
      requestJson("/api/live/jobs", { method: "POST" }),
    ).rejects.toMatchObject({ status: 502, outcomeUnknown: true });
    globalThis.fetch = async () => new Response("not json", { status: 200 });
    await expect(api("example")).rejects.toThrow("unreadable response");
    globalThis.fetch = async () =>
      new Response('{"detail":[null,{}, {"msg":17}]}', { status: 422 });
    await expect(api("example")).rejects.toThrow("API is unavailable");
  } finally {
    globalThis.fetch = original;
  }
});
