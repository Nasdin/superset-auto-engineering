import { test, expect } from "@playwright/test";

test("a broken view preserves navigation and can recover after a route change", async ({
  page,
}) => {
  await page.route("**/api/analytics/pull-requests?*", async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.impact = null;
    await route.fulfill({ json: data });
  });
  await page.goto("/#analytics");
  await expect(
    page.getByRole("heading", { name: "This view could not be displayed" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Reload page", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Workflows", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Workflow lanes" }),
  ).toBeVisible();
  await page.unroute("**/api/analytics/pull-requests?*");
  await page.getByRole("button", { name: "Analytics", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "What changed after launch?" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "This view could not be displayed" }),
  ).toHaveCount(0);
});

test("login recovers from a proxy failure and keeps the workspace closed until authenticated", async ({
  page,
}) => {
  let authenticated = false;
  let loginAttempts = 0;
  await page.route("**/api/auth/session", (route) =>
    route.fulfill({ json: { enabled: true, authenticated } }),
  );
  await page.route("**/api/auth/login", async (route) => {
    loginAttempts++;
    if (loginAttempts === 1) {
      await route.fulfill({
        status: 502,
        contentType: "text/html",
        body: "<h1>Proxy unavailable</h1>",
      });
    } else if (loginAttempts === 2) {
      await route.fulfill({
        status: 401,
        json: { detail: "Incorrect password" },
      });
    } else {
      authenticated = true;
      await route.fulfill({ json: { authenticated: true } });
    }
  });
  await page.route("**/api/auth/logout", async (route) => {
    authenticated = false;
    await route.fulfill({ json: { authenticated: false } });
  });
  await page.goto("/");
  await page.getByLabel("Workspace password").fill("test-password");
  await page.getByRole("button", { name: "Open workspace" }).click();
  await expect(page.getByRole("alert")).toContainText("Unable to sign in");
  await expect(page.getByRole("navigation", { name: "Workspace" })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Open workspace" }).click();
  await expect(page.getByRole("alert")).toContainText("Incorrect password");
  await page.getByRole("button", { name: "Open workspace" }).click();
  await expect(
    page.getByRole("navigation", { name: "Workspace" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByLabel("Workspace password")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Workspace" })).toHaveCount(
    0,
  );
});
