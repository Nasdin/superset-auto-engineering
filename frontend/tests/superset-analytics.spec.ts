import { test, expect, type Response } from "@playwright/test";

test("real Superset impact charts match cohorts, switch cadence and isolate repositories", async ({
  page,
}) => {
  test.skip(
    !process.env.SUPERSET_ANALYTICS_E2E,
    "Requires provisioned BI Superset",
  );
  test.setTimeout(240_000);
  page.on("pageerror", (error) => console.log("Browser error:", error.message));
  let responses: Response[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/v1/chart/data?"))
      responses.push(response);
  });
  async function checkCharts(query: string) {
    const frame = page.frameLocator("iframe");
    for (const name of [
      "Hours to merge",
      "Commits per PR",
      "Rework after review",
      "Lines changed per PR",
      "Total hours before merge · calendar month",
      "Total merge hours by work type · calendar month",
      "Merged changes · current window",
    ]) {
      await page.locator(".superset-panel").scrollIntoViewIfNeeded();
      await frame
        .locator('[data-test="span-title"]')
        .filter({ hasText: name })
        .scrollIntoViewIfNeeded({ timeout: 30_000 });
    }
    await expect
      .poll(
        () => responses.filter((r) => !r.request().frame().isDetached()).length,
        { timeout: 60_000 },
      )
      .toBeGreaterThanOrEqual(7);
    const captured = responses.filter((r) => !r.request().frame().isDetached());
    const charts = await Promise.all(
      captured.map(async (r) => {
        expect(r.status()).toBe(200);
        const body = await r.json();
        for (const result of body.result) expect(result.status).toBe("success");
        return {
          ...body.result[0],
          metric: r.request().postDataJSON()?.queries?.[0]?.metrics?.[0],
        };
      }),
    );
    const reference = await (
      await page.request.get(`/api/analytics/pull-requests?${query}`)
    ).json();
    const trendCharts = charts.filter((c) => c.colnames.includes("chart_date"));
    expect(trendCharts).toHaveLength(6);
    const comparisonCharts = trendCharts.filter(
      (c) => !["total_hours", "segment_total_hours"].includes(c.metric),
    );
    const mergeTrend = trendCharts.find((c) => c.metric === "median_hours");
    expect(mergeTrend).toBeDefined();
    if (!query.includes("cadence=rolling")) {
      for (const expected of reference.impact.monthly) {
        const actual = mergeTrend.data.find(
          (r: { chart_date: number }) =>
            new Date(r.chart_date).toISOString().slice(0, 10) ===
            expected.month,
        );
        expect(actual).toBeDefined();
        if (expected.covered && expected.median_hours !== null)
          expect(actual[expected.segment]).toBeCloseTo(
            expected.median_hours,
            8,
          );
        else expect(actual[expected.segment]).toBeNull();
      }
    }
    const monthlyTotal = trendCharts.find((c) => c.metric === "total_hours");
    expect(monthlyTotal).toBeDefined();
    for (const expected of reference.impact.monthly_totals) {
      const actual = monthlyTotal.data.find(
        (r: { chart_date: number }) =>
          new Date(r.chart_date).toISOString().slice(0, 10) === expected.month,
      );
      expect(actual).toBeDefined();
      if (expected.covered_total_hours === null)
        expect(actual["All selected PRs"]).toBeNull();
      else
        expect(actual["All selected PRs"]).toBeCloseTo(
          expected.covered_total_hours,
          8,
        );
    }
    const categoryTotal = trendCharts.find(
      (c) => c.metric === "segment_total_hours",
    );
    expect(categoryTotal).toBeDefined();
    for (const expected of reference.impact.monthly) {
      const actual = categoryTotal.data.find(
        (r: { chart_date: number }) =>
          new Date(r.chart_date).toISOString().slice(0, 10) === expected.month,
      );
      expect(actual).toBeDefined();
      if (expected.covered_total_hours === null)
        expect(actual[expected.segment]).toBeNull();
      else
        expect(actual[expected.segment]).toBeCloseTo(
          expected.covered_total_hours,
          8,
        );
    }
    for (const chart of comparisonCharts) {
      expect(
        chart.annotation_data?.["System introduced"]?.records?.[0]?.start_dttm,
      ).toBeTruthy();
      for (const segment of reference.impact.categories.map(
        (c: { segment: string }) => c.segment,
      ))
        expect(chart.colnames).toContain(segment);
    }
    for (const name of [
      "Hours to merge",
      "Commits per PR",
      "Rework after review",
      "Lines changed per PR",
    ])
      await expect(
        frame.locator('[data-test="span-title"]').filter({ hasText: name }),
      ).toBeVisible();
    await expect(frame.getByText("Data error", { exact: true })).toHaveCount(0);
    await expect(
      frame.getByText("Unexpected error", { exact: false }),
    ).toHaveCount(0);
    return { charts, reference };
  }
  await page.goto("/#analytics");
  if (process.env.AUTH_E2E_PASSWORD) {
    await page
      .getByLabel("Workspace password")
      .fill(process.env.AUTH_E2E_PASSWORD);
    await page.getByRole("button", { name: "Open workspace" }).click();
  }
  await expect(
    page.getByRole("heading", { name: "Engineering impact" }),
  ).toBeVisible();
  const initial = await checkCharts("repository=apache%2Fsuperset");
  console.log(
    JSON.stringify({
      monthly_chart_columns: initial.charts
        .filter((c) => c.colnames.includes("chart_date"))
        .map((c) => c.colnames),
      current: initial.reference.impact.current,
    }),
  );
  await page.screenshot({
    path: "test-results/engineering-impact-desktop.png",
    fullPage: true,
  });
  responses = [];
  await page
    .getByRole("button", { name: "Rolling window", exact: true })
    .click();
  await checkCharts("repository=apache%2Fsuperset&cadence=rolling");
  responses = [];
  await page.getByText("Analysis controls", { exact: true }).click();
  await page.getByRole("slider").fill("60");
  await checkCharts("repository=apache%2Fsuperset&days=60&cadence=rolling");
  responses = [];
  await page.getByText("Refine cohort", { exact: true }).click();
  await page.getByLabel("Work signal").selectOption("bot");
  await checkCharts(
    "repository=apache%2Fsuperset&days=60&kind=bot&cadence=rolling",
  );
  responses = [];
  await page
    .getByRole("combobox", { name: "Repository", exact: true })
    .selectOption("Nasdin/superset");
  await checkCharts(
    "repository=Nasdin%2Fsuperset&days=60&kind=bot&cadence=rolling",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel("Work signal").selectOption("");
  responses = [];
  await page
    .getByRole("combobox", { name: "Repository", exact: true })
    .selectOption("apache/superset");
  await checkCharts("repository=apache%2Fsuperset&days=60&cadence=rolling");
  const cards = page.frameLocator("iframe").locator(".chart-slice");
  const first = await cards.nth(0).boundingBox();
  const second = await cards.nth(1).boundingBox();
  expect(first?.width).toBeGreaterThan(270);
  expect(second!.y).toBeGreaterThan(first!.y + first!.height);
  // Full-width cards can still contain a stale half-width ECharts canvas.
  // Check the actual rendering surface, not just the surrounding grid layout.
  for (let index = 0; index < 4; index++) {
    const chart = cards.nth(index);
    await chart.scrollIntoViewIfNeeded();
    await expect
      .poll(
        () =>
          chart.evaluate((element) => {
            const canvas = element.querySelector("canvas");
            return (
              (canvas?.getBoundingClientRect().width || 0) /
              element.getBoundingClientRect().width
            );
          }),
        { timeout: 15_000 },
      )
      .toBeGreaterThan(0.8);
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/engineering-impact-mobile.png",
    fullPage: true,
  });
});
