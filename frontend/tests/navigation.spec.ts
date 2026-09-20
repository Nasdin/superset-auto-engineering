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
  for (const name of ["Evidence", "Workflows", "Analytics", "Operations"])
    await expect(
      primary.getByRole("button", { name, exact: true }),
    ).toBeVisible();
  await page.getByRole("button", { name: "PR evidence", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Every change has a story." }),
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
  await expect(
    page.getByRole("heading", { name: "Autonomy, with a paper trail." }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Dependabot runs", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Dependency updates, with proof." }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Learning & memory", exact: true })
    .click();
  await expect(page).toHaveURL(/#learning$/);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Learning & memory", exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Dependency updates, with proof." }),
  ).toBeVisible();
  await primary
    .getByRole("button", { name: "Operations", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "From a real issue to reviewable proof.",
    }),
  ).toBeVisible();
  await primary.getByRole("button", { name: "Analytics", exact: true }).click();
  await expect(
    page.getByRole("combobox", { name: "Repository", exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await primary.getByRole("button", { name: "Workflows", exact: true }).click();
  const learning = page.getByRole("button", {
    name: "Learning & memory",
    exact: true,
  });
  await learning.focus();
  await page.keyboard.press("Enter");
  await expect(learning).toHaveAttribute("aria-pressed", "true");
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
