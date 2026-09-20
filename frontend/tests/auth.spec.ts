import { test, expect } from "@playwright/test";

test("workspace login rejects wrong passwords, persists refresh, and revokes logout", async ({
  page,
  context,
}) => {
  test.skip(
    !process.env.AUTH_E2E_PASSWORD,
    "Requires an auth-enabled local server",
  );
  const gateway = process.env.AUTH_GATEWAY_URL;
  if (gateway) {
    expect((await page.request.get(`${gateway}/bi/health`)).status()).toBe(401);
    const redirect = await page.request.get(`${gateway}/bi/`, {
      headers: { Accept: "text/html" },
      maxRedirects: 0,
    });
    expect(redirect.status()).toBe(303);
    expect(redirect.headers().location).toBe("/?login=1");
  }
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Welcome back." }),
  ).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Workspace" })).toHaveCount(
    0,
  );
  expect((await page.request.get("/api/live/overview")).status()).toBe(401);
  await page.getByLabel("Workspace password").fill("incorrect-test-password");
  await page.getByRole("button", { name: "Open workspace" }).click();
  await expect(page.getByRole("alert")).toContainText("Incorrect password");
  await page
    .getByLabel("Workspace password")
    .fill(process.env.AUTH_E2E_PASSWORD!);
  await page.getByRole("button", { name: "Open workspace" }).click();
  await expect(
    page.getByRole("navigation", { name: "Workspace" }),
  ).toBeVisible();
  const cookie = (await context.cookies()).find(
    (item) => item.name === "cognition_session",
  );
  expect(cookie?.httpOnly).toBe(true);
  if (gateway)
    expect((await page.request.get(`${gateway}/bi/health`)).status()).toBe(200);
  await page.reload();
  await expect(
    page.getByRole("navigation", { name: "Workspace" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome back." }),
  ).toBeVisible();
  expect((await page.request.get("/api/live/overview")).status()).toBe(401);
  await context.addCookies([cookie!]);
  expect((await page.request.get("/api/live/overview")).status()).toBe(401);
  if (gateway)
    expect((await page.request.get(`${gateway}/bi/health`)).status()).toBe(401);
  await context.clearCookies();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await expect(page.getByLabel("Workspace password")).toBeVisible();
  await page.screenshot({
    path: "test-results/login-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: "test-results/login-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
});
