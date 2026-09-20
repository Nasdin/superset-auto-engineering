import { test, expect } from "@playwright/test";
test("inspect evidence, persist a review, queue an event and navigate views", async ({
  page,
}) => {
  await page.goto("/?demo=1");
  await expect(
    page.getByRole("heading", { name: "Confidence, backed by evidence." }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Critical browser journeys Sign in" })
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "No Superset browser was executed",
  );
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Review candidate" }).click();
  await page
    .getByLabel("Review notes")
    .fill("Browser test reviewed the demo fixtures.");
  await page.getByRole("button", { name: "Record demo approval" }).click();
  await expect(page.getByRole("status")).toContainText("Demo decision saved");
  await page.getByRole("button", { name: "Workflows", exact: true }).click();
  await page.getByPlaceholder("Search workflows…").fill("empty query");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page.getByRole("button", { name: "Simulate issue event" }).click();
  await page.getByLabel("Issue title").fill("Browser smoke test issue");
  await page.getByRole("button", { name: "Queue demo event" }).click();
  await expect(page.getByRole("status")).toContainText("Demo event queued");
  await page.reload();
  await page.getByRole("button", { name: "Analytics", exact: true }).click();
  await expect(
    page.getByText("Browser smoke test issue").first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Devin runs", exact: true }).click();
  await page
    .getByRole("button", { name: "View session trace" })
    .first()
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "not a real Devin session",
  );
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Repository graph", exact: true })
    .click();
  await page.getByRole("button", { name: "Evidence gate" }).click();
  await expect(
    page.getByRole("heading", { name: "Confidence, backed by evidence." }),
  ).toBeVisible();
  await expect(
    page.getByText("Demo approval recorded", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("heading", { name: "Confidence, backed by evidence." })
    .click();
  await page.setViewportSize({ width: 1440, height: 1120 });
  await page.screenshot({
    path: "test-results/dashboard-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("button", { name: "Review candidate" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/dashboard-mobile.png",
    fullPage: true,
  });
});
test("API outage shows retry instead of fake success", async ({ page }) => {
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({ status: 503, body: "unavailable" }),
  );
  await page.goto("/?demo=1");
  await expect(page.getByRole("alert")).toContainText("API is unavailable");
  await expect(
    page.getByRole("button", { name: "Retry connection" }),
  ).toBeVisible();
});

test("live operations shows real ledger and configuration state", async ({
  page,
}) => {
  await page.goto("/?demo=1");
  await page
    .getByRole("button", { name: "Live operations", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Workspace health",
    }),
  ).toBeVisible();
  await expect(
    page
      .getByLabel("Integration configuration")
      .getByRole("heading", { name: "GitHub" }),
  ).toBeVisible();
  await expect(page.getByText("WF-041", { exact: true })).toHaveCount(0);
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.screenshot({
    path: "test-results/live-operations.png",
    animations: "disabled",
    fullPage: true,
  });
});

test("dashboard recovers after an unavailable response", async ({ page }) => {
  await page.route(
    "**/api/dashboard",
    (route) => route.fulfill({ status: 503, body: "unavailable" }),
    { times: 1 },
  );
  await page.goto("/?demo=1");
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: "Retry connection" }).click();
  await expect(
    page.getByRole("heading", { name: "Confidence, backed by evidence." }),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("live polling skips overlaps and refresh keeps the latest response", async ({
  page,
  request,
}) => {
  const baseline = await (await request.get("/api/live/overview")).json();
  await page.clock.install();
  let requests = 0;
  let releaseFirst!: () => void;
  const firstBlocked = new Promise<void>((resolve) => {
    releaseFirst = resolve;
  });
  await page.route("**/api/live/overview", async (route) => {
    requests++;
    if (requests === 1) {
      await firstBlocked;
      await route
        .fulfill({ json: { ...baseline, repository: "old-response" } })
        .catch(() => {});
    } else {
      await route.fulfill({
        json: { ...baseline, repository: "latest-response" },
      });
    }
  });
  await page.goto("/?demo=1");
  await page
    .getByRole("button", { name: "Live operations", exact: true })
    .click();
  await expect.poll(() => requests).toBe(1);
  await page.clock.fastForward(15_000);
  expect(requests).toBe(1);
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(
    page.locator("summary").filter({ hasText: "latest-response" }),
  ).toBeVisible();
  releaseFirst();
  await expect(page.getByText("old-response", { exact: false })).toHaveCount(0);
  await page.getByRole("button", { name: "Analytics", exact: true }).click();
  const countOnLeave = requests;
  await page.clock.fastForward(15_000);
  expect(requests).toBe(countOnLeave);
});
