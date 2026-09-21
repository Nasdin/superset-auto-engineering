import { test, expect, type Response } from "@playwright/test";

test("native Superset delivery and rework charts match bounded cohorts across dates, repositories and layouts", async ({
  page,
}) => {
  test.skip(
    !process.env.SUPERSET_ANALYTICS_E2E,
    "Requires provisioned BI Superset",
  );
  test.setTimeout(300_000);
  let responses: Response[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/v1/chart/data?"))
      responses.push(response);
  });
  const focus = ["Fixes", "Features", "Bots"];
  async function checkCharts(query: string, panel = "delivery") {
    const metrics =
      panel === "delivery"
        ? [
            "avg_commits",
            "median_hours",
            "avg_rework",
            "avg_lines_changed",
            "segment_total_hours",
          ]
        : ["avg_rework", "avg_lines_changed", "avg_additions", "avg_deletions"];
    const titles = page
      .frameLocator("iframe")
      .locator('[data-test="span-title"]');
    await expect(titles).toHaveCount(metrics.length, { timeout: 30_000 });
    for (const title of await titles.all())
      await title.scrollIntoViewIfNeeded();
    await expect
      .poll(
        () => responses.filter((r) => !r.request().frame().isDetached()).length,
        { timeout: 60_000 },
      )
      .toBeGreaterThanOrEqual(metrics.length);
    const captured = responses.filter((r) => !r.request().frame().isDetached());
    const charts = await Promise.all(
      captured.map(async (response) => {
        expect(response.status()).toBe(200);
        const body = await response.json();
        for (const result of body.result) expect(result.status).toBe("success");
        return {
          ...body.result[0],
          metric: response.request().postDataJSON()?.queries?.[0]?.metrics?.[0],
        };
      }),
    );
    const reference = await (
      await page.request.get(
        `/api/analytics/pull-requests?bounded=true&days=180&${query}`,
      )
    ).json();
    for (const metric of metrics) {
      const chart = charts.find((c) => c.metric === metric);
      expect(chart, metric).toBeDefined();
      expect(
        chart.colnames.filter((name: string) => name !== "chart_date").sort(),
      ).toEqual([...focus].sort());
      expect(
        chart.annotation_data?.["System introduced"]?.records?.[0]?.start_dttm,
      ).toBeTruthy();
      const cadence =
        query.includes("cadence=weekly") && metric !== "segment_total_hours"
          ? "weekly"
          : "monthly";
      for (const row of reference.impact[cadence].filter(
        (r: { segment: string }) => focus.includes(r.segment),
      )) {
        const actual = chart.data.find(
          (r: { chart_date: number }) =>
            new Date(r.chart_date).toISOString().slice(0, 10) === row.month,
        );
        expect(actual).toBeDefined();
        const expected = !row.covered
          ? null
          : metric === "segment_total_hours"
            ? row.covered_total_hours
            : metric === "avg_additions"
              ? row.code_samples
                ? row.additions / row.code_samples
                : null
              : metric === "avg_deletions"
                ? row.code_samples
                  ? row.deletions / row.code_samples
                  : null
                : row[metric];
        if (expected === null) expect(actual[row.segment]).toBeNull();
        else expect(actual[row.segment]).toBeCloseTo(expected, 7);
      }
    }
    await expect(
      page.frameLocator("iframe").getByText("Data error", { exact: true }),
    ).toHaveCount(0);
    console.log(
      JSON.stringify({
        panel,
        query,
        charts: metrics.length,
        parity: "passed",
      }),
    );
  }
  await page.goto("/#analytics");
  if (process.env.AUTH_E2E_PASSWORD) {
    await page
      .getByLabel("Workspace password")
      .fill(process.env.AUTH_E2E_PASSWORD);
    await page.getByRole("button", { name: "Open workspace" }).click();
  }
  await expect(
    page.getByRole("heading", { name: "What changed after launch?" }),
  ).toBeVisible();
  await checkCharts("repository=apache%2Fsuperset");
  await page.setViewportSize({ width: 1513, height: 1033 });
  await page
    .getByRole("heading", { name: "What changed after launch?" })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: "test-results/analytics-focus-desktop.png",
    fullPage: true,
  });
  responses = [];
  await page.getByRole("button", { name: "Week", exact: true }).click();
  await checkCharts("repository=apache%2Fsuperset&cadence=weekly");
  responses = [];
  await page.getByRole("tab", { name: "Rework & code", exact: true }).click();
  await checkCharts("repository=apache%2Fsuperset&cadence=weekly", "rework");
  responses = [];
  await page
    .getByRole("combobox", { name: "Repository", exact: true })
    .selectOption("Nasdin/superset");
  await checkCharts("repository=Nasdin%2Fsuperset&cadence=weekly", "rework");
  responses = [];
  await page.getByRole("tab", { name: "Delivery", exact: true }).click();
  await page.getByRole("button", { name: "Month", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await checkCharts("repository=Nasdin%2Fsuperset");
  const cards = page.frameLocator("iframe").locator(".chart-slice");
  const first = await cards.nth(0).boundingBox();
  const second = await cards.nth(1).boundingBox();
  expect(first?.width).toBeGreaterThan(270);
  expect(second!.y).toBeGreaterThan(first!.y + first!.height);
  for (let i = 0; i < 4; i++) {
    const chart = cards.nth(i);
    await chart.scrollIntoViewIfNeeded();
    await expect
      .poll(() =>
        chart.evaluate(
          (element) =>
            (element.querySelector("canvas")?.getBoundingClientRect().width ||
              0) / element.getBoundingClientRect().width,
        ),
      )
      .toBeGreaterThan(0.8);
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/analytics-focus-mobile.png",
    fullPage: true,
  });
  await page.getByRole("tab", { name: "Impact estimate", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "What this estimate means" }),
  ).toBeVisible();
  await expect(page.locator("iframe")).toHaveCount(0);
});
