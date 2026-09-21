import { test, expect } from "@playwright/test";
const summary =
  "Reproduced the column metadata probe executing twice against the target database. Removed the redundant execution and verified the regression on the candidate revision. ".repeat(
    7,
  ) + "Final evidence remains linked to this exact revision.";
const run = {
  id: "source-a",
  kind: "repair",
  state: "implemented",
  payload: { title: "Avoid duplicate column metadata queries" },
  session_url: "https://app.devin.ai/sessions/source-a",
  candidate_sha: "a".repeat(40),
  pr_number: 5,
  acu: 1,
  created: 1789862400,
  updated: 1789862400,
  result: { summary, checks: [], artifacts: [] },
  error: null,
};
const observation = {
  job_id: run.id,
  kind: run.kind,
  status: "reported",
  title: run.payload.title,
  summary,
  candidate_sha: run.candidate_sha,
  pr_number: 5,
  session_url: run.session_url,
};
const base = {
  repository: "Nasdin/superset",
  branch: "cognition-release-6.1",
  sync: { state: "connected", at: 1789862400 },
  jobs: [
    run,
    {
      ...run,
      id: "later",
      kind: "validation",
      state: "review_ready",
      payload: {
        title: "Validate the integrated candidate",
        implementation_jobs: [run.id],
      },
      parent_id: run.id,
    },
  ],
  lessons: [
    {
      id: "latest-note",
      created: 1789862400,
      native_state: "confirmed",
      note_id: "note-" + "a".repeat(70),
      observation,
    },
    {
      id: "old-note",
      created: 1789776000,
      native_state: "retired",
      note_id: "retired-note",
      observation: {
        ...observation,
        title: "Old superseded observation",
        summary: "Earlier report",
      },
    },
    {
      id: "validation-note",
      created: 1789866000,
      native_state: "confirmed",
      note_id: "validation-native-note",
      observation: {
        ...observation,
        job_id: "later",
        kind: "validation",
        status: "validated",
        title: "Independent release checks passed",
        summary:
          "The candidate passed database, API, browser and regression checks.",
      },
    },
  ],
  contexts: [
    {
      job_id: "later",
      created: 1789866000,
      memories: [
        { lesson_id: "latest-note", knowledge_id: "native-note", observation },
      ],
    },
    {
      job_id: "not-dispatched",
      created: 1789867000,
      memories: [
        { lesson_id: "latest-note", knowledge_id: "native-note", observation },
      ],
    },
  ],
  cohorts: [{ month: "2026-09", passed: 1, failed: 0 }],
};

test("compact learning journal preserves complete evidence and survives polling", async ({
  page,
}) => {
  let data = structuredClone(base);
  let fail = false;
  await page.route("**/api/live/learning", (r) =>
    r.fulfill(
      fail
        ? { status: 503, json: { detail: "Learning temporarily unavailable" } }
        : { json: data },
    ),
  );
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/#learning");
  await page
    .getByRole("button", { name: "Run observations", exact: true })
    .click();
  const primary = page.getByRole("navigation", { name: "Workspace" });
  await expect(primary.getByRole("button")).toHaveCount(4);
  await expect(
    primary.getByRole("button", { name: "Learning", exact: true }),
  ).toHaveCount(0);
  await expect(
    primary.getByRole("button", { name: "Workflows", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page
      .getByRole("group", { name: "Workflows views" })
      .getByRole("button", { name: "Learning", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  const journal = page.getByRole("region", {
    name: "Memory journal",
    exact: true,
  });
  await expect(
    journal.getByRole("button", { name: /Read observation:/ }),
  ).toHaveCount(2);
  await expect(page.getByText("Old superseded observation")).toHaveCount(0);
  const metric = page
    .getByRole("region", { name: "Learning overview" })
    .locator("article")
    .filter({
      has: page.getByRole("heading", {
        name: "Sessions supplied memories",
        exact: true,
      }),
    });
  await expect(metric.locator("strong")).toHaveText("1");
  await expect(page.locator(".memory-preview").first()).toHaveCSS(
    "-webkit-line-clamp",
    "2",
  );
  await page.screenshot({
    path: "test-results/learning-journal-desktop.png",
    fullPage: true,
  });
  const row = page.getByRole("button", {
    name: "Read observation: " + run.payload.title,
    exact: true,
  });
  await row.click();
  const detail = page.getByRole("region", {
    name: "Observation details",
    exact: true,
  });
  await expect(detail).toBeFocused();
  await expect(detail.locator(".memory-full-summary")).toHaveText(summary);
  await expect(detail.getByRole("link", { name: "PR #5" })).toHaveAttribute(
    "href",
    "https://github.com/Nasdin/superset/pull/5",
  );
  await detail.getByText("Record identifiers", { exact: true }).click();
  await expect(
    detail.getByText("note-" + "a".repeat(70), { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(
    detail.getByText("note-" + "a".repeat(70), { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Refresh", exact: true }),
  ).toBeFocused();
  data = {
    ...data,
    lessons: [
      {
        ...data.lessons[0],
        id: "new-version",
        created: 1789869000,
        observation: {
          ...observation,
          summary: "Updated result on the same source run.",
        },
      },
      ...data.lessons,
    ],
  };
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(detail.locator(".memory-full-summary")).toHaveText(
    "Updated result on the same source run.",
  );
  await detail
    .getByRole("button", { name: "Inspect source & evidence" })
    .click();
  await expect(
    page.getByRole("region", { name: "Source run & evidence" }),
  ).toBeFocused();
  await page
    .getByRole("region", { name: "Source run & evidence" })
    .getByRole("button", { name: "Close details" })
    .click();
  await detail.getByRole("button", { name: "Close details" }).click();
  await expect(row).toBeFocused();
  await page.getByLabel("Search observations").fill("#5");
  await expect(
    journal.getByRole("button", { name: /Read observation:/ }),
  ).toHaveCount(2);
  await page.getByText("Filter observations", { exact: true }).click();
  await page.getByLabel("Outcome", { exact: true }).selectOption("validated");
  await expect(
    journal.getByRole("button", { name: /Read observation:/ }),
  ).toHaveCount(1);
  await page.getByLabel("Search observations").fill("no matches");
  await expect(
    page.getByText("No observations match these filters."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(
    journal.getByRole("button", { name: /Read observation:/ }),
  ).toHaveCount(2);
  fail = true;
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Showing the last received records",
  );
  await expect(
    journal.getByRole("button", { name: /Read observation:/ }),
  ).toHaveCount(2);
});

test("learning details fit a phone and missing sources are explicit", async ({
  page,
}) => {
  await page.route("**/api/live/learning", (r) =>
    r.fulfill({
      json: { ...base, jobs: [], lessons: [base.lessons[0]], contexts: [] },
    }),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#learning");
  await page
    .getByRole("button", { name: "Run observations", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "Read observation: " + run.payload.title,
      exact: true,
    })
    .click();
  const detail = page.getByRole("region", {
    name: "Observation details",
    exact: true,
  });
  await detail.getByText("Record identifiers", { exact: true }).click();
  await expect(
    detail.getByRole("button", { name: "Inspect source & evidence" }),
  ).toBeDisabled();
  await expect(detail.getByText(/source run is outside/)).toBeVisible();
  await expect(detail.getByRole("link", { name: "Open Devin" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/learning-detail-mobile.png",
    fullPage: true,
  });
});

test("an outcome update cannot close the selected observation during refresh", async ({
  page,
}) => {
  let data = structuredClone(base);
  await page.route("**/api/live/learning", (r) => r.fulfill({ json: data }));
  await page.goto("/#learning");
  await page
    .getByRole("button", { name: "Run observations", exact: true })
    .click();
  await page.getByText("Filter observations", { exact: true }).click();
  await page.getByLabel("Outcome", { exact: true }).selectOption("reported");
  await page
    .getByRole("button", {
      name: "Read observation: " + run.payload.title,
      exact: true,
    })
    .click();
  const detail = page.getByRole("region", {
    name: "Observation details",
    exact: true,
  });
  await detail.getByText("Record identifiers", { exact: true }).click();
  data = {
    ...data,
    lessons: [
      {
        ...data.lessons[0],
        id: "updated-outcome",
        created: 1789869000,
        observation: { ...observation, status: "stale" },
      },
      ...data.lessons,
    ],
  };
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(detail).toBeVisible();
  await expect(detail.getByText("stale", { exact: true })).toBeVisible();
  await expect(
    detail.getByText("note-" + "a".repeat(70), { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("status")).toContainText("details remain open");
  await expect(
    page.getByRole("button", { name: "Refresh", exact: true }),
  ).toBeFocused();
  await page.getByLabel("Outcome", { exact: true }).selectOption("validated");
  await expect(detail.getByText("stale", { exact: true })).toHaveCount(0);
});
