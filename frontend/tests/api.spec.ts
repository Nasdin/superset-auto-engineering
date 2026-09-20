import { test, expect } from "@playwright/test";
import { api } from "../src/api";
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
    expect(options?.signal).toBe(controller.signal);
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
