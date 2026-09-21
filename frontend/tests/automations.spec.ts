import { test, expect } from "@playwright/test";
const job = {
  id: "scan-one",
  kind: "scan",
  state: "running",
  payload: { title: "Discover a defect", source: "manual" },
  created: 1,
  updated: 1,
  acu: 0,
  error: null,
  session_url: "https://app.devin.ai/sessions/test",
  result: null,
};
const data = {
  repository: "Nasdin/superset",
  branch: "cognition-release-6.1",
  enabled: true,
  schedule: {
    id: "discovery",
    name: "Autonomous correctness scan",
    enabled: 1,
    interval_seconds: 86400,
    next_run: 2000000000,
    updated: 12,
    last_job_id: null,
  },
  worker: { state: "running" },
  holds: [],
  active: [],
  history: [job],
  sessions_used: 4,
  session_limit: 6,
  max_acu: 10,
  triggers: [],
  webhook: { configured: true, count: 1, last_received: 1 },
};

test("operator controls preserve manual retry intent and never persist the key", async ({
  page,
}) => {
  await page.route("**/api/live/automations", (r) => r.fulfill({ json: data }));
  await page.route("**/api/live/operator", (r) =>
    r.fulfill({ json: { authenticated: true } }),
  );
  const intents: string[] = [];
  await page.route("**/api/live/scan", (r) => {
    intents.push(r.request().postDataJSON().request_id);
    return r.fulfill(
      intents.length === 1
        ? { status: 503, json: { detail: "Temporarily unavailable" } }
        : { json: { id: "scan-one", state: "queued" } },
    );
  });
  let saved: unknown;
  await page.route("**/api/live/schedules/discovery", (r) => {
    saved = r.request().postDataJSON();
    return r.fulfill({ json: data.schedule });
  });
  await page.goto("/#automations");
  const run = page.getByRole("button", { name: "Run discovery now" });
  await expect(run).toBeDisabled();
  await page.getByText("Execution access", { exact: true }).click();
  await page.getByLabel("Operator key").fill("test-operator");
  await page.getByRole("button", { name: "Unlock execution controls" }).click();
  await expect(run).toBeEnabled();
  await run.click();
  await expect(page.getByRole("alert")).toContainText(
    "Temporarily unavailable",
  );
  await run.click();
  await expect(page.getByRole("status")).toContainText("queued");
  expect(intents).toHaveLength(2);
  expect(intents[0]).toBe(intents[1]);
  await page.getByText("Edit schedule", { exact: true }).click();
  await page
    .getByRole("combobox", { name: "Cadence", exact: true })
    .selectOption("604800");
  await page.getByRole("button", { name: "Save schedule" }).click();
  expect(saved).toMatchObject({
    interval_seconds: 604800,
    expected_updated: 12,
  });
  expect(
    await page.evaluate(() =>
      JSON.stringify({ ...localStorage, ...sessionStorage }),
    ),
  ).not.toContain("test-operator");
  await page.reload();
  await expect(run).toBeDisabled();
});

test("selected discovery follows fresh polling data", async ({ page }) => {
  let state = "running";
  await page.route("**/api/live/automations", (r) =>
    r.fulfill({ json: { ...data, history: [{ ...job, state }] } }),
  );
  await page.goto("/#automations");
  await page.getByRole("button", { name: /Discover a defect/ }).click();
  const region = page.getByRole("region", { name: "Selected discovery" });
  await expect(region).toContainText("running");
  state = "completed";
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(region).toContainText("completed");
});

test("uncertain resume never claims success or changes retry intent", async ({
  page,
}) => {
  await page.route("**/api/live/automations", (r) =>
    r.fulfill({
      json: {
        ...data,
        holds: [{ ...job, state: "needs_attention", error: "Suspended" }],
      },
    }),
  );
  await page.route("**/api/live/operator", (r) =>
    r.fulfill({ json: { authenticated: true } }),
  );
  const intents: string[] = [];
  await page.route("**/api/live/jobs/*/resume", (r) => {
    intents.push(r.request().postDataJSON().request_id);
    return r.fulfill({ json: { status: "unknown_effect", job_id: job.id } });
  });
  await page.goto("/#automations");
  await page.getByText("Execution access", { exact: true }).click();
  await page.getByLabel("Operator key").fill("test-operator");
  await page.getByRole("button", { name: "Unlock execution controls" }).click();
  await page.getByRole("button", { name: "Resume same session" }).click();
  await expect(page.getByRole("alert")).toContainText("uncertain");
  await expect(page.getByRole("status")).toHaveCount(0);
  await page.getByRole("button", { name: "Resume same session" }).click();
  expect(intents[0]).toBe(intents[1]);
});

test("catalogue persists controls, attributes runs and retains retry intent", async ({
  page,
}) => {
  let recipe = {
    id: "code_patterns",
    name: "Code Pattern Enforcer",
    description: "Fork conventions",
    category: "Engineering",
    kind: "scan",
    enabled: 0,
    interval_seconds: 604800,
    next_run: 2000000000,
    updated: 10,
    run_count: 2,
    configuration_required: null,
  };
  let stale = false;
  const child = {
    ...job,
    id: "repair-one",
    kind: "repair",
    payload: { title: "Repair convention drift", source: "scheduled_scan" },
    automations: [{ id: recipe.id, name: recipe.name }],
  };
  await page.route("**/api/live/automations", (r) =>
    r.fulfill(
      stale
        ? { status: 503, json: { detail: "Unavailable" } }
        : {
            json: {
              ...data,
              catalogue: [
                recipe,
                {
                  ...recipe,
                  id: "cloudflare_audit",
                  enabled: 0,
                  name: "Cloudflare Security Audit",
                  kind: "audit",
                  configuration_required: "Configure read-only audit access",
                },
              ],
              automation_history: [
                child,
                {
                  ...job,
                  id: "other",
                  payload: { title: "Other recipe" },
                  automations: [{ id: "discovery", name: "Discovery" }],
                },
              ],
            },
          },
    ),
  );
  await page.route("**/api/live/operator", (r) =>
    r.fulfill({ json: { authenticated: true } }),
  );
  await page.route("**/api/live/schedules/code_patterns", (r) => {
    const body = r.request().postDataJSON();
    expect(body.expected_updated).toBe(recipe.updated);
    recipe = {
      ...recipe,
      enabled: Number(body.enabled),
      interval_seconds: body.interval_seconds,
      updated: recipe.updated + 1,
    };
    return r.fulfill({ json: recipe });
  });
  const intents: string[] = [];
  await page.route("**/api/live/automations/code_patterns/run", (r) => {
    intents.push(r.request().postDataJSON().request_id);
    return r.fulfill(
      intents.length === 1
        ? { status: 503, json: { detail: "Temporarily unavailable" } }
        : { json: { ...job, state: "queued" } },
    );
  });
  await page.goto("/#automations");
  const enable = page.getByRole("button", {
    name: "Enable Code Pattern Enforcer",
  });
  await expect(enable).toBeDisabled();
  await page.getByText("Execution access", { exact: true }).click();
  await page.getByLabel("Operator key").fill("test-operator");
  await page.getByRole("button", { name: "Unlock execution controls" }).click();
  await enable.click();
  const pause = page.getByRole("button", {
    name: "Pause Code Pattern Enforcer",
  });
  await expect(pause).toBeEnabled();
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(pause).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "Enable Cloudflare Security Audit" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Run Cloudflare Security Audit now" }),
  ).toBeDisabled();
  const run = page.getByRole("button", {
    name: "Run Code Pattern Enforcer now",
  });
  await run.click();
  await expect(page.getByRole("alert")).toContainText(
    "Temporarily unavailable",
  );
  await run.click();
  await expect(page.getByRole("status")).toContainText(
    "queue record is not yet a started",
  );
  expect(intents).toHaveLength(2);
  expect(intents[0]).toBe(intents[1]);
  const history = page.getByRole("region", { name: "Automation runs" });
  await expect(history).toContainText("Repair convention drift");
  await expect(history).not.toContainText("Other recipe");
  await history
    .getByRole("button", { name: /Repair convention drift/ })
    .click();
  await expect(
    page.getByRole("region", { name: "Automation run", exact: true }),
  ).toContainText("Code Pattern Enforcer");
  stale = true;
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(run).toBeDisabled();
  await expect(pause).toBeDisabled();
});
