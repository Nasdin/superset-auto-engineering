import { test, expect } from "@playwright/test";

test("impact shows measurement gaps and an explicit adjustable effort scenario", async ({
  page,
}) => {
  await page.route("**/api/analytics/pull-requests?*", async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.impact.estimate = {
      eligible_prs: 4,
      covered: true,
      by_segment: { Fixes: 4, Features: 0, Bots: 0, Other: 0 },
    };
    await route.fulfill({ json: data });
  });
  await page.goto("/#analytics");
  await expect(
    page.getByRole("heading", { name: "Engineering impact" }),
  ).toBeVisible();
  await expect(page.getByLabel("System rollout")).toContainText(
    "21 September 2026",
  );
  await expect(
    page.locator(".impact-kpi").getByText("Commits per PR", { exact: true }),
  ).toBeVisible();
  const model = page.getByLabel("Estimated time saved", { exact: true });
  await expect(model).toContainText("6 engineering hours");
  await model.getByLabel("Manual implementation + review / PR").fill("1");
  await expect(model).toContainText("2 engineering hours");
  await model.getByLabel("Human oversight with Devin / PR").fill("2");
  await expect(model).toContainText("-4 engineering hours");
  await model.getByLabel("Human oversight with Devin / PR").fill("");
  await expect(model.getByRole("alert")).toBeVisible();
  await expect(model).toContainText("— engineering hours");
  await page.getByRole("button", { name: "Baseline", exact: true }).click();
  await expect(page.locator(".impact-table caption")).toContainText(
    "UTC merge dates",
  );
  await page
    .getByText("Before / after launch & measurement notes", { exact: true })
    .click();
  await expect(
    page.getByText("The marker is a rollout date", { exact: false }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});
