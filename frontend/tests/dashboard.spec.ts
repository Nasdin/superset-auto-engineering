import { test, expect } from "@playwright/test";
test("inspect evidence, persist a review, queue an event and navigate views", async ({
  page,
}) => {
  await page.goto("/");
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
    path: "../evidence/dashboard-desktop.png",
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
    path: "../evidence/dashboard-mobile.png",
    fullPage: true,
  });
});
test("API outage shows retry instead of fake success", async ({ page }) => {
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({ status: 503, body: "unavailable" }),
  );
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("API is unavailable");
  await expect(
    page.getByRole("button", { name: "Retry connection" }),
  ).toBeVisible();
});
