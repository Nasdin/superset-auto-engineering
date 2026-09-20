import { test, expect, type Response } from "@playwright/test";

test("real guest Superset charts match Postgres cohorts and isolate repository filters", async ({
  page,
}) => {
  test.skip(
    !process.env.SUPERSET_ANALYTICS_E2E,
    "Requires running Postgres and provisioned BI Superset",
  );
  test.setTimeout(180_000);
  let responses: Response[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/v1/chart/data?"))
      responses.push(response);
  });
  const checkCharts = async (query: string) => {
    await expect
      .poll(() => responses.length, { timeout: 45_000 })
      .toBeGreaterThanOrEqual(6);
    const charts = await Promise.all(
      responses.map(async (response) => {
        expect(response.status()).toBe(200);
        const body = await response.json();
        for (const result of body.result) expect(result.status).toBe("success");
        return body.result[0];
      }),
    );
    const referenceResponse = await page.request.get(
      `/api/analytics/pull-requests?${query}`,
    );
    expect(referenceResponse.ok()).toBeTruthy();
    const reference = await referenceResponse.json();
    const metric = (name: string) =>
      charts.find((chart) => chart.colnames.includes(name))?.data[0]?.[name];
    expect(metric("current_median_hours")).toBe(reference.current.median_hours);
    expect(metric("baseline_median_hours")).toBe(
      reference.baseline.median_hours,
    );
    const change = metric("median_change_percent");
    if (reference.change_percent === null) expect(change).toBeNull();
    else expect(change).toBeCloseTo(reference.change_percent, 8);
    const cohorts = charts.find((chart) =>
      chart.colnames.includes("cohort"),
    )?.data;
    expect(
      cohorts.find((row: { cohort: string }) => row.cohort === "Current")
        .merged_prs,
    ).toBe(reference.current.merged);
    const frame = page.frameLocator("iframe");
    await expect(
      frame.getByText("Current median · hours", { exact: true }),
    ).toBeVisible();
    await expect(
      frame.getByText("Unexpected error", { exact: false }),
    ).toHaveCount(0);
  };
  await page.goto("/");
  if (process.env.AUTH_E2E_PASSWORD) {
    await page
      .getByLabel("Workspace password")
      .fill(process.env.AUTH_E2E_PASSWORD);
    await page.getByRole("button", { name: "Open workspace" }).click();
  }
  await page.getByRole("button", { name: "Analytics", exact: true }).click();
  await checkCharts("repository=apache%2Fsuperset");
  await page.screenshot({
    path: "test-results/superset-analytics-live.png",
    fullPage: true,
  });
  responses = [];
  await page.getByRole("slider").fill("60");
  await checkCharts("repository=apache%2Fsuperset&days=60");
  responses = [];
  await page.getByRole("slider").fill("30");
  await checkCharts("repository=apache%2Fsuperset&days=30");
  responses = [];
  await page.getByLabel("Work signal").selectOption("dependency");
  await checkCharts("repository=apache%2Fsuperset&kind=dependency");
  responses = [];
  await page
    .getByRole("combobox", { name: "Repository", exact: true })
    .selectOption("Nasdin/superset");
  await checkCharts("repository=Nasdin%2Fsuperset&kind=dependency");
  await page.screenshot({
    path: "test-results/superset-analytics-fork.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});
