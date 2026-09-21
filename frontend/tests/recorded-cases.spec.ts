import { expect, test } from "@playwright/test";

test("recorded cases keep historical proof separate from current release readiness", async ({
  page,
}) => {
  await page.goto("/#evidence");
  const proof = page.getByRole("region", {
    name: "Recorded engineering demonstrations",
  });
  await expect(proof.getByText("586", { exact: true })).toBeVisible();
  await expect(
    proof.getByText("Recorded gate passed · human merge remains separate"),
  ).toBeVisible();
  await expect(
    proof.getByText(/saved checkpoint, not a live readiness signal/),
  ).toBeVisible();
  await expect(
    proof.getByRole("link", { name: "Read the PR evidence report" }),
  ).toHaveAttribute("href", /pull\/10#issuecomment/);
  await proof
    .getByRole("button", { name: "Human change → Devin repair" })
    .click();
  await expect(proof.getByText("557", { exact: true })).toBeVisible();
  await expect(
    proof.getByText("Runtime checks passed · CI pending at this checkpoint"),
  ).toBeVisible();
  await expect(
    proof.getByRole("img", {
      name: "Before · 04bff00 · six rows, wrong result",
    }),
  ).toBeVisible();
  await expect(
    proof.getByRole("img", {
      name: "After · a118efc7 · five rows, correct result",
    }),
  ).toBeVisible();
  await proof.getByText("Watch Devin’s browser recording").click();
  await expect(proof.locator("video")).toHaveAttribute("preload", "none");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
