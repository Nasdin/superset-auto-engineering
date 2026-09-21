import { expect, test } from "@playwright/test";

// Simulated API responses: this verifies presentation, not live Devin execution.
test("Dependabot queue explains the blocking session and distinguishes recorded SHA readiness", async ({
  page,
}) => {
  const sha = "a".repeat(40);
  const session = "https://app.devin.ai/sessions/paused-fixture";
  const message =
    "Minor gaps: final logout screenshot missing due to a session suspension.";
  const blocker = {
    code: "session_hold",
    pr_number: 6,
    state: "needs_attention",
    message,
    session_url: session,
  };
  let ready = false;
  await page.route("**/api/live/pull-requests?*", async (route) => {
    await route.fulfill({
      json: {
        repository: "Nasdin/superset",
        branch: "cognition-release-6.1",
        enabled: true,
        sync: {},
        poll: {},
        total: 1,
        offset: 0,
        limit: 50,
        execution: {
          enabled: true,
          dependabot_enabled: true,
          sessions_used: 5,
          sessions_limit: 20,
          sessions_remaining: 15,
          max_acu_per_session: 20,
          worker: { at: 1790000000 },
          blockers: ready ? [] : [blocker],
        },
        rows: [
          {
            number: 6,
            title: "chore: bump PyJWT",
            author: "dependabot[bot]",
            dependabot: true,
            category: "dependency",
            state: "open",
            runs: ready
              ? [
                  {
                    id: "validator",
                    kind: "validation",
                    state: "review_ready",
                    candidate_sha: sha,
                    result: {
                      summary: "Independent fixture validation",
                      checks: [],
                      artifacts: [],
                    },
                    payload: {},
                  },
                ]
              : [],
            publications: ready
              ? [
                  {
                    key: "github:validator:6:revision",
                    state: "sent",
                    purpose: "report",
                    url: "https://github.com/Nasdin/superset/pull/6#issuecomment-1",
                  },
                  {
                    key: `github-ready:validator:${sha}:revision`,
                    state: "sent",
                    purpose: "readiness",
                    url: "https://github.com/Nasdin/superset/pull/6",
                  },
                ]
              : [],
            progress: ready
              ? {
                  state: "review_ready",
                  label: "Evidence ready for review",
                  ready: true,
                  candidate_sha: sha,
                  observed_at: 1790000000,
                  validation_pr: 6,
                  session_url:
                    "https://app.devin.ai/sessions/validator-fixture",
                  detail:
                    "Independent evidence and GitHub CI passed for this PR at the recorded SHA. Confirm the current head and merge requirements on GitHub.",
                }
              : {
                  state: "queued",
                  label: "Queued · waiting for execution",
                  ready: false,
                  detail: message,
                  blocker,
                },
          },
        ],
      },
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Workflows", exact: true }).click();
  await page
    .getByRole("button", { name: "Dependabot runs", exact: true })
    .click();
  const queue = page.getByRole("region", { name: "Execution queue" });
  await expect(queue).toContainText(
    "5 of 20 session slots used · 15 remaining",
  );
  await expect(queue).toContainText("not the Devin credit balance");
  await expect(queue).toContainText(message);
  await expect(
    queue.getByRole("link", { name: "Open blocking Devin session" }),
  ).toHaveAttribute("href", session);
  await expect(
    page.getByRole("link", { name: "View blocking run" }),
  ).toHaveAttribute("href", session);
  await expect(
    page.getByText("Evidence ready for review", { exact: true }),
  ).toHaveCount(0);

  ready = true;
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(
    page.getByText("Evidence ready for review", { exact: true }),
  ).toBeVisible();
  await expect(page.getByTitle(sha)).toHaveText(sha.slice(0, 12));
  await expect(
    page.getByRole("link", { name: "Open Devin session" }),
  ).toHaveAttribute("href", /validator-fixture$/);
  await page.getByRole("button", { name: "#6 chore: bump PyJWT" }).click();
  await expect(
    page.getByRole("region", { name: "Recorded release gate" }),
  ).toContainText("New commits require a fresh gate");
  await expect(
    page.getByRole("link", { name: "Published report" }),
  ).toHaveAttribute("href", /issuecomment-1$/);
  await expect(
    page.getByRole("link", { name: "PR readiness confirmed" }),
  ).toHaveAttribute("href", /pull\/6$/);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});
