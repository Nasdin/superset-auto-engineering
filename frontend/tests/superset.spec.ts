import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
test("real pinned Superset signs in and queries the seeded MySQL fixture", async ({
  browser,
}) => {
  test.skip(
    process.env.SUPERSET_E2E !== "1",
    "Requires isolated Superset validation stack",
  );
  test.setTimeout(60_000);
  const config = Object.fromEntries(
    readFileSync("../.env.superset", "utf8")
      .split("\n")
      .filter((s) => s.includes("="))
      .map((s) => s.split("=")),
  );
  const context = await browser.newContext({
    recordVideo: {
      dir: "../evidence/superset-browser",
      size: { width: 1280, height: 800 },
    },
    viewport: { width: 1280, height: 800 },
  });
  const page = await context.newPage();
  try {
    await page.goto("http://127.0.0.1:8188/login/");
    await page.screenshot({ path: "../evidence/superset-login.png" });
    // Use the visible accessible labels from the rendered Superset form.
    await page.getByRole("textbox", { name: "Username:" }).fill("validator");
    await page
      .getByRole("textbox", { name: "Password:" })
      .fill(config.VALIDATION_ADMIN_PASSWORD);
    await page.getByRole("button", { name: /sign in|login/i }).click();
    await expect(page).not.toHaveURL(/\/login/);
    await page.goto("http://127.0.0.1:8188/sqllab/");
    const firstTab = page.getByRole("tab", {
      name: "Add a new tab plus-circle",
    });
    await expect(
      firstTab.or(page.getByRole("button", { name: "Add tab", exact: true })),
    ).toBeVisible({ timeout: 20_000 });
    if (await firstTab.isVisible()) await firstTab.click();
    else
      await page.getByRole("button", { name: "Add tab", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "mysql Cognition MySQL", exact: true }),
    ).toBeVisible();
    const editor = page.getByRole("textbox", { name: /^Cursor at row/ });
    await editor.focus();
    await editor.press("ControlOrMeta+A");
    await editor.pressSequentially(
      "SELECT COUNT(*) AS fixture_count, SUM(value) AS total_value FROM validation.grain_fixture;",
      { delay: 5 },
    );
    await page
      .getByRole("button", { name: "caret-right Run", exact: true })
      .click();
    await expect(
      page.getByRole("columnheader", { name: /fixture_count/ }),
    ).toBeVisible({ timeout: 15000 });
    await expect(
      page.getByRole("gridcell", { name: "3", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("gridcell", { name: "6", exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: "../evidence/superset-sql-lab.png",
      fullPage: true,
    });
  } finally {
    await context.close();
  }
  await page.video()!.saveAs("../evidence/superset-baseline.webm");
  await page.video()!.delete();
});
