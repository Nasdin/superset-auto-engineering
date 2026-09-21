import { test, expect } from "@playwright/test";

test("collapsed controls keep context and keyboard access across refresh", async ({
  page,
}) => {
  await page.goto("/#analytics");
  const controls = page.locator(".analysis-controls");
  const summary = controls.locator("summary").first();
  await expect(
    page.getByRole("combobox", { name: "Repository", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Window end (UTC)")).toBeHidden();
  await expect(summary).toContainText("apache/superset");
  await page
    .getByRole("combobox", { name: "Time range", exact: true })
    .selectOption("90");
  await expect(summary).toContainText("90 days");
  const bots = page
    .getByRole("group", { name: "Work type", exact: true })
    .getByRole("button", { name: "Bots", exact: true });
  await bots.click();
  await expect(bots).toHaveAttribute("aria-pressed", "true");
  await expect(summary).toContainText("bot");
  await bots.click();
  await expect(bots).toHaveAttribute("aria-pressed", "false");
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("combobox", { name: "Repository", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Rolling window:", { exact: false }).fill("60");
  await page.getByText("Refine cohort", { exact: true }).click();
  await page.getByLabel("Work signal").selectOption("bot");
  await summary.click();
  await expect(
    page.getByRole("combobox", { name: "Time range", exact: true }),
  ).toHaveValue("60");
  await expect(summary).toContainText("60 days");
  await expect(summary).toContainText("bot");
  await page.getByText("Page tools", { exact: true }).click();
  await page.getByRole("button", { name: "Refresh data", exact: true }).click();
  await expect(controls).not.toHaveAttribute("open");
  await summary.click();
  await expect(page.getByLabel("Work signal")).toHaveValue("bot");
  await page
    .getByRole("button", { name: "Reset filters", exact: true })
    .click();
  await expect(page.getByLabel("Work signal")).toHaveValue("");
  await expect(
    page.getByLabel("Rolling window:", { exact: false }),
  ).toHaveValue("30");
});

test("inspection brings evidence into focus and close returns to its trigger", async ({
  page,
  request,
}) => {
  const baseline = await (await request.get("/api/live/overview")).json();
  const job = {
    id: "attention-test",
    kind: "validation",
    lane: "Integration & validation",
    state: "blocked",
    session_url: null,
    candidate_sha: "a".repeat(40),
    pr_number: 7,
    error: "Validation stopped; review required",
    acu: 0,
    created: 1,
    updated: 1,
    started: null,
    parent_id: null,
    payload: { title: "Inspect this candidate" },
  };
  await page.route("**/api/live/overview", (route) =>
    route.fulfill({ json: { ...baseline, jobs: [job] } }),
  );
  await page.goto("/#workflows");
  const trigger = page.getByRole("button", { name: /Inspect this candidate/ });
  await trigger.click();
  const region = page.getByRole("region", {
    name: "Selected run",
    exact: true,
  });
  await expect(region).toBeFocused();
  await expect(region).toContainText("Validation stopped; review required");
  await page
    .getByRole("button", { name: "Close details", exact: true })
    .click();
  await expect(region).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await page.goto("/#operations");
  await expect(page.getByLabel("Queue attention")).toContainText(
    "Validation stopped; review required",
  );
  await expect(
    page
      .locator("details")
      .filter({ has: page.getByText("Workflow ledger", { exact: true }) }),
  ).not.toHaveAttribute("open");
});

test("every workspace view fits desktop and phone with discoverable controls", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  if (process.env.AUTH_E2E_PASSWORD) {
    await page
      .getByLabel("Workspace password")
      .fill(process.env.AUTH_E2E_PASSWORD);
    await page.getByRole("button", { name: "Open workspace" }).click();
  }
  const views = [
    ["evidence", "Release validation", "Change candidate"],
    ["pull-requests", "Pull request evidence", "Filter pull requests"],
    ["lineage", "Repository lineage", "Filter records"],
    ["workflows", "Workflow lanes", "Filter records"],
    ["automations", "Automations", "Edit schedule"],
    ["runs", "Devin runs", "Filter records"],
    ["dependencies", "Dependency updates", "Filter pull requests"],
    ["learning", "Learning & memory", "Filter observations"],
    ["analytics", "Engineering impact", "Analysis controls"],
    ["operations", "Workspace health", "Operating configuration"],
  ];
  for (const [slug, title, control] of views) {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/#" + slug);
    await expect(
      page.getByRole("heading", { name: title, exact: true }).first(),
    ).toBeVisible();
    await expect(page.getByText(control, { exact: true })).toBeVisible();
    if (slug === "analytics")
      await expect(page.locator(".impact-kpi")).toHaveCount(4);
    const disclosure = page
      .locator("details")
      .filter({ has: page.getByText(control, { exact: true }) })
      .first();
    await expect(disclosure).not.toHaveAttribute("open");
    await page.screenshot({
      path: `test-results/workspace-${slug}-desktop.png`,
      fullPage: true,
      animations: "disabled",
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByText(control, { exact: true }).click();
    await expect(disclosure).toHaveAttribute("open");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      slug,
    ).toBeTruthy();
    await page.getByText(control, { exact: true }).click();
    await page.screenshot({
      path: `test-results/workspace-${slug}-mobile.png`,
      fullPage: true,
      animations: "disabled",
    });
  }
  expect(errors).toEqual([]);
});
