import { test, expect } from "@playwright/test";

test("default workspace only loads live records, with honest empty states", async ({
  page,
}) => {
  const fixtureRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/dashboard"))
      fixtureRequests.push(request.url());
  });
  await page.goto("/");
  await expect(
    page.getByText("No validation candidate yet.", { exact: false }),
  ).toBeVisible();
  await expect(page.getByText("Demo data", { exact: true })).toHaveCount(0);
  await expect(page.getByText("WF-041")).toHaveCount(0);
  for (const name of ["Workflows", "Devin runs", "Repository graph"]) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(
      page.getByText("No live records match these filters."),
    ).toBeVisible();
  }
  expect(fixtureRequests).toEqual([]);
});

test("real API cohorts drive filters, comparison, chart and linked PR rows", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Analytics", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Is the work getting faster?" }),
  ).toBeVisible();
  await expect(page.getByText("50.0%", { exact: true })).toBeVisible();
  await expect(
    page.getByText("shorter time to merge", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: /#1 fix: browser analytics/ }),
  ).toBeVisible();
  await page.getByLabel("Work signal").selectOption("dependency");
  await expect(
    page.getByText("No merged PRs in this window.", { exact: false }),
  ).toBeVisible();
  await expect(page.getByText("50.0%", { exact: true })).toHaveCount(0);
  await page.getByLabel("Work signal").selectOption("fix");
  await page
    .getByRole("combobox", { name: "Author", exact: true })
    .selectOption("test-engineer");
  await page
    .getByRole("combobox", { name: "Label", exact: true })
    .selectOption("bug");
  await page.getByLabel("Base branch").selectOption("master");
  await expect(page.getByText("50.0%", { exact: true })).toBeVisible();
  await page.getByLabel("Attribution").selectOption("tracked");
  await expect(page.getByText("Not enough comparable data")).toBeVisible();
  await page.getByLabel("Attribution").selectOption("all");
  await page.getByLabel("Compare with").selectOption("previous");
  await expect(page.getByText("Not enough comparable data")).toBeVisible();
  await page.getByLabel("Compare with").selectOption("six_months");
  await expect(page.getByText("50.0%", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.screenshot({
    path: "test-results/real-analytics-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/real-analytics-mobile.png",
    fullPage: true,
  });
  await page.getByLabel("Repository").selectOption("Nasdin/superset");
  await expect(
    page.getByText("GitHub history has not been imported.", { exact: false }),
  ).toBeVisible();
  await expect(page.getByText("50.0%", { exact: true })).toHaveCount(0);
});
