import { test, expect } from "@playwright/test";

const snapshot = {
  worker: { state: "running", at: 1789928112, stale: false },
  retry_policy: { max_attempts: 5, base_seconds: 30, max_seconds: 1800 },
  breakers: [
    {
      provider: "devin",
      state: "open",
      reason: "Credit balance unavailable",
      failures: 3,
      retry_at: 2000000000,
    },
  ],
  jobs: [
    {
      id: "retained-session",
      kind: "validation",
      state: "dead_letter",
      session_id: "existing-devin-session",
      error: "Observation attempts exhausted",
      recovery: {
        attempts: 5,
        stage: "poll",
        category: "transient",
        replay_state: "running",
      },
    },
    {
      id: "ambiguous-create",
      kind: "repair",
      state: "unknown_effect",
      error: "Session creation was not confirmed",
      recovery: { attempts: 1, category: "unknown_effect" },
    },
  ],
  inbox: [
    {
      id: "event-retry",
      state: "dead_letter",
      error: "GitHub read failed",
      next_retry: 2000000000,
      created: 1,
      updated: 2,
      recovery: { attempts: 5, stage: "intake", category: "transient" },
    },
    {
      id: "event-uncertain",
      state: "unknown_effect",
      error: "Outcome unconfirmed",
      created: 1,
      updated: 2,
    },
  ],
  publications: [
    {
      key: "pr:confirmed-failure",
      state: "failed",
      error: "Rate limited",
      recovery: { attempts: 2, category: "transient" },
    },
    {
      key: "slack:ambiguous-send",
      state: "unknown_effect",
      error: "Delivery not confirmed",
      recovery: { attempts: 1, category: "unknown_effect" },
    },
  ],
  durability: {
    database: "postgresql",
    single_worker: true,
    backups_enabled: false,
  },
  counts: {
    retrying: 1,
    dead_letters: 1,
    held: 1,
    uncertain: 2,
    pending_publications: 2,
  },
};

test("recovery is owner-only, reuses uncertain request intents and never replays ambiguous writes", async ({
  page,
}) => {
  await page.route("**/api/live/resilience", (r) =>
    r.fulfill({ json: snapshot }),
  );
  await page.route("**/api/live/operator", (r) =>
    r.fulfill({ json: { authenticated: true } }),
  );
  const inboxRequests: string[] = [];
  await page.route("**/api/live/recovery/inbox/event-retry", (r) => {
    inboxRequests.push(r.request().postDataJSON().request_id);
    return r.fulfill({
      json: { status: "requeued", delivery_id: "event-retry" },
    });
  });
  const requests: string[] = [];
  await page.route("**/api/live/recovery/jobs/retained-session", (r) => {
    expect(r.request().headers().authorization).toBe("Bearer test-operator");
    requests.push(r.request().postDataJSON().request_id);
    return r.fulfill(
      requests.length === 1
        ? { status: 503, json: { detail: "Recovery response unavailable" } }
        : { json: { status: "requeued", job_id: "retained-session" } },
    );
  });
  await page.goto("/#workflows");
  const panel = page.getByRole("region", { name: "Workflow reliability" });
  await expect(panel).toContainText("Dead letters");
  const disclosure = panel.locator("details").first();
  await expect(disclosure).not.toHaveAttribute("open", "");
  await panel.getByText("Recovery & durability", { exact: true }).click();
  await expect(panel).toContainText("Backups are disabled");
  const retry = panel.getByRole("button", { name: "Retry observation" });
  await expect(retry).toBeDisabled();
  await expect(
    panel.getByRole("button", { name: "Retry intake" }),
  ).toBeDisabled();
  for (const id of [
    "ambiguous-create",
    "slack:ambiguous-send",
    "event-uncertain",
  ]) {
    const row = panel.locator("article").filter({ hasText: id });
    await expect(row).toContainText("Reconciliation required · no replay");
    await expect(row.getByRole("button")).toHaveCount(0);
  }
  await panel.getByText("Execution access", { exact: true }).click();
  await panel.getByLabel("Operator key").fill("test-operator");
  await panel
    .getByRole("button", { name: "Unlock execution controls" })
    .click();
  await expect(retry).toBeEnabled();
  await retry.click();
  await expect(panel.getByRole("alert")).toHaveText(
    "Recovery response unavailable",
  );
  await retry.click();
  await expect(panel.getByRole("status")).toContainText(
    "Recovery request recorded",
  );
  await panel.getByRole("button", { name: "Retry intake" }).click();
  expect(inboxRequests).toHaveLength(1);
  expect(requests).toHaveLength(2);
  expect(requests[0]).toBe(requests[1]);
  expect(requests[0]).toMatch(/^[\da-f-]{36}$/);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page
    .getByRole("button", { name: "Release gates", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Release reliability" }),
  ).toContainText(
    "A passed validation and a delivered PR or Slack report are separate facts.",
  );
});

test("missing worker heartbeat and unavailable reliability data cannot look healthy", async ({
  page,
}) => {
  await page.route("**/api/live/resilience", (r) =>
    r.fulfill({
      json: {
        ...snapshot,
        worker: { state: "running", at: 1000, stale: true },
      },
    }),
  );
  await page.goto("/#workflows");
  const panel = page.getByRole("region", { name: "Workflow reliability" });
  await expect(panel).toContainText("Worker heartbeat overdue");
  await page.route("**/api/live/resilience", (r) =>
    r.fulfill({ status: 503, json: { detail: "Database unavailable" } }),
  );
  await expect(panel.getByRole("alert")).toContainText(
    "Last known values below may be stale",
    { timeout: 15000 },
  );
  await expect(panel).toContainText("Status unavailable");
});
