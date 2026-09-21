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
  await model.getByText("Estimate assumptions", { exact: true }).click();
  await model.getByLabel("Manual implementation + review / PR").fill("1");
  await expect(model).toContainText("2 engineering hours");
  await model.getByLabel("Human oversight with Devin / PR").fill("2");
  await expect(model).toContainText("-4 engineering hours");
  await model.getByLabel("Human oversight with Devin / PR").fill("");
  await expect(model.getByRole("alert")).toBeVisible();
  await expect(model).toContainText("— engineering hours");
  await page.getByRole("button", { name: "Baseline", exact: true }).click();
  await expect(
    page.locator(".impact-comparison .impact-table caption"),
  ).toContainText("UTC merge dates");
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

test("repository selection stays visible and never presents the previous cohort while loading", async ({
  page,
  request,
}) => {
  const reference = await (
    await request.get("/api/analytics/pull-requests")
  ).json();
  let release: () => void = () => {};
  const holdFork = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/analytics/pull-requests?*", async (route) => {
    const repo = new URL(route.request().url()).searchParams.get("repository");
    if (repo === "example/superset") await holdFork;
    await route.fulfill({
      json: {
        ...reference,
        repository: repo,
        repositories: ["apache/superset", "example/superset"],
        workflow_repository: "example/superset",
      },
    });
  });
  await page.goto("/#analytics");
  const repository = page.getByRole("combobox", {
    name: "Repository",
    exact: true,
  });
  await expect(repository).toBeVisible();
  await expect(page.locator(".analysis-controls")).not.toHaveAttribute("open");
  await expect(repository.locator("option")).toHaveCount(2);
  await expect(page.locator(".impact-kpi")).toHaveCount(4);
  await repository.selectOption("example/superset");
  await expect(
    page.getByText("Loading the selected GitHub cohort…"),
  ).toBeVisible();
  await expect(page.locator(".impact-kpi")).toHaveCount(0);
  await expect(page.locator(".superset-panel")).toHaveCount(0);
  release();
  await expect(page.locator(".impact-kpi")).toHaveCount(4);
  await expect(repository).toHaveValue("example/superset");
  await expect(page.getByLabel("Analytics repository")).toContainText(
    "Automation always runs in example/superset",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(repository).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});

test("missing history explains queued imports and withholds unknown totals while verified empty months show zero", async ({
  page,
  request,
}) => {
  const reference = await (
    await request.get("/api/analytics/pull-requests")
  ).json();
  const measure = reference.impact.current;
  await page.route("**/api/analytics/pull-requests?*", (route) =>
    route.fulfill({
      json: {
        ...reference,
        backfill: {
          state: "loading",
          pending_months: 2,
          months: [
            {
              month: "2026-04-01",
              state: "queued",
              covered_through: null,
              requested_through: "2026-04-30",
              next_retry: 0,
            },
            {
              month: "2026-05-01",
              state: "retry",
              covered_through: null,
              requested_through: "2026-05-31",
              next_retry: 1800000000,
            },
            {
              month: "2026-06-01",
              state: "ready",
              covered_through: "2026-06-30",
              requested_through: "2026-06-30",
              next_retry: 0,
            },
          ],
        },
        impact: {
          ...reference.impact,
          monthly_totals: [
            {
              ...measure,
              month: "2026-04-01",
              covered: false,
              covered_total_hours: null,
              merged_prs: 0,
              merge_samples: 0,
            },
            {
              ...measure,
              month: "2026-06-01",
              covered: true,
              covered_total_hours: 0,
              merged_prs: 0,
              merge_samples: 0,
            },
          ],
        },
      },
    }),
  );
  await page.goto("/#analytics");
  const coverage = page.getByRole("region", { name: "Historical coverage" });
  await expect(coverage.getByRole("status")).toContainText(
    "Loading missing months from GitHub",
  );
  await expect(coverage).toContainText("2 months pending");
  await coverage.getByText("Monthly import progress").click();
  await expect(coverage).toContainText("Retry scheduled");
  await expect(coverage).toContainText("No verified coverage yet");
  await page.getByText("Monthly sample coverage", { exact: true }).click();
  const totals = page.getByRole("table", {
    name: "Total hours before merge · calendar months",
  });
  await expect(
    totals.getByRole("row").filter({ hasText: "2026-04" }),
  ).toContainText("—");
  await expect(
    totals.getByRole("row").filter({ hasText: "2026-04" }),
  ).toContainText("Incomplete · total withheld");
  await expect(
    totals
      .getByRole("row")
      .filter({ hasText: "2026-06" })
      .getByRole("cell")
      .first(),
  ).toHaveText("0");
  await expect(page.locator(".merge-hours-definition")).toContainText(
    "not engineering labour or time saved",
  );
});
