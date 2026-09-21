import { test, expect } from "@playwright/test";

test("four workspaces retain every feature, deep links and mobile navigation", async ({
  page,
}) => {
  await page.goto("/");
  if (process.env.AUTH_E2E_PASSWORD) {
    await page
      .getByLabel("Workspace password")
      .fill(process.env.AUTH_E2E_PASSWORD);
    await page.getByRole("button", { name: "Open workspace" }).click();
  }
  await page.setViewportSize({ width: 1440, height: 1100 });
  await expect(
    page.getByRole("heading", { name: "Release evidence gate", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/consolidated-evidence-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
  const primary = page.getByRole("navigation", { name: "Workspace" });
  await expect(primary.getByRole("button")).toHaveCount(4);
  for (const name of ["Evidence", "Workflows", "Analytics", "System"])
    await expect(
      primary.getByRole("button", { name, exact: true }),
    ).toBeVisible();
  await page.getByRole("button", { name: "PR evidence", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Pull request evidence" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Repository graph", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Workflow lineage" }),
  ).toBeVisible();
  await primary.getByRole("button", { name: "Workflows", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Workflow lanes" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Devin runs", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Devin runs" })).toBeVisible();
  await page
    .getByRole("button", { name: "Dependabot runs", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Dependency updates" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Learning", exact: true }).click();
  await expect(page).toHaveURL(/#learning$/);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Learning & memory", exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Dependency updates" }),
  ).toBeVisible();
  await primary.getByRole("button", { name: "System", exact: true }).click();
  await expect(
    page.getByRole("heading", {
      name: "Workspace health",
    }),
  ).toBeVisible();
  await primary.getByRole("button", { name: "Analytics", exact: true }).click();
  await expect(
    page.getByText("Analysis controls", { exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Skip to content" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#analytics$/);
  await expect(page.locator("main")).toBeFocused();
  await primary.getByRole("button", { name: "Workflows", exact: true }).click();
  await page.goBack();
  await expect(page).toHaveURL(/#analytics$/);
  await expect(
    page.getByText("Analysis controls", { exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await primary.getByRole("button", { name: "Workflows", exact: true }).click();
  const learning = page.getByRole("button", {
    name: "Learning",
    exact: true,
  });
  await learning.focus();
  await page.keyboard.press("Enter");
  await expect(learning).toHaveAttribute("aria-pressed", "true");
  await expect(
    primary.getByRole("button", { name: "Workflows", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page.getByRole("heading", { name: "Learning & memory", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/consolidated-navigation-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
});
