import { test, expect } from "@playwright/test";

test("explicit dates apply atomically and all analytics tabs retain the selected cohort", async ({
  page,
}) => {
  const queries: URLSearchParams[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/analytics/pull-requests?"))
      queries.push(new URL(request.url()).searchParams);
  });
  await page.goto("/#analytics");
  await expect(
    page.getByRole("region", { name: "Key metrics comparison" }),
  ).toBeVisible();
  await page.getByLabel("Choose dates").click();
  const before = queries.length;
  await page.getByLabel("Start date", { exact: true }).fill("2026-04-12");
  await page.getByLabel("End date", { exact: true }).fill("2026-06-03");
  expect(queries.length).toBe(before);
  await page.getByRole("button", { name: "Apply dates" }).click();
  await expect.poll(() => queries.at(-1)?.get("end")).toBe("2026-06-03");
  expect(queries.at(-1)?.get("days")).toBe("53");
  expect(queries.at(-1)?.get("bounded")).toBe("true");
  await expect(page.getByLabel("Choose dates")).toContainText(
    "Apr 12, 2026 – Jun 3, 2026",
  );
  await page.getByRole("button", { name: "Week", exact: true }).click();
  await expect.poll(() => queries.at(-1)?.get("cadence")).toBe("weekly");
  const rework = page.getByRole("tab", { name: "Rework & code", exact: true });
  await rework.click();
  await expect(rework).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tabpanel")).toHaveAttribute(
    "aria-labelledby",
    "tab-rework",
  );
  await rework.press("ArrowRight");
  await expect(
    page.getByRole("tab", { name: "Impact estimate", exact: true }),
  ).toBeFocused();
  await expect(
    page.getByRole("heading", { name: "What this estimate means" }),
  ).toBeVisible();
  await expect(page.locator(".superset-panel")).toHaveCount(0);
  await expect(page.getByLabel("Choose dates")).toContainText(
    "Apr 12, 2026 – Jun 3, 2026",
  );
  await page
    .getByRole("tab", { name: "Impact estimate", exact: true })
    .press("Home");
  const table = page.getByRole("region", { name: "Key metrics comparison" });
  await expect(table.getByRole("columnheader")).toHaveText([
    "Selected period",
    "Fixes",
    "Features",
    "Bots",
  ]);
});

test("date picker rejects ranges longer than one year without making a request", async ({
  page,
}) => {
  await page.goto("/#analytics");
  await page.getByLabel("Choose dates").click();
  await page.getByLabel("Start date", { exact: true }).fill("2024-01-01");
  await page.getByLabel("End date", { exact: true }).fill("2026-01-01");
  await page.getByRole("button", { name: "Apply dates" }).click();
  await expect(
    page.locator(".date-range-control").getByRole("alert"),
  ).toContainText("1–366 completed UTC days");
  await expect(page.locator(".date-range-control")).toHaveAttribute("open");
});

test("a historical preset-length range remains custom and can return to the latest preset", async ({
  page,
}) => {
  await page.goto("/#analytics");
  await page.getByLabel("Choose dates").click();
  await page.getByLabel("Start date", { exact: true }).fill("2026-04-01");
  await page.getByLabel("End date", { exact: true }).fill("2026-04-30");
  await page.getByRole("button", { name: "Apply dates" }).click();
  await page.getByLabel("Choose dates").click();
  await expect(page.getByLabel("Time range", { exact: true })).toHaveValue(
    "custom",
  );
  await page.getByLabel("Time range", { exact: true }).selectOption("30");
  await expect(page.getByLabel("Choose dates")).not.toContainText(
    "Apr 1, 2026",
  );
  await expect(page.locator(".date-range-control")).not.toHaveAttribute("open");
});
