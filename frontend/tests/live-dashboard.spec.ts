import { test, expect } from "@playwright/test";

test("default workspace only loads live records, with honest empty states", async ({
  page,
}) => {
  const fixtureRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/dashboard"))
      fixtureRequests.push(request.url());
  });
  await page.goto("/");
  await expect(
    page.getByText("No validation candidate yet.", { exact: false }),
  ).toBeVisible();
  await expect(page.getByText("Demo data", { exact: true })).toHaveCount(0);
  await expect(page.getByText("WF-041")).toHaveCount(0);
  for (const name of ["Workflows", "Devin runs", "Repository graph"]) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(
      page.getByText("No live records match these filters."),
    ).toBeVisible();
  }
  expect(fixtureRequests).toEqual([]);
});

test("real API cohorts drive filters, comparison, chart and linked PR rows", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Analytics", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Is the work getting faster?" }),
  ).toBeVisible();
  await expect(page.getByText("50.0%", { exact: true })).toBeVisible();
  await expect(
    page.getByText("shorter time to merge", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: /#1 fix: browser analytics/ }),
  ).toBeVisible();
  await page.getByLabel("Work signal").selectOption("dependency");
  await expect(
    page.getByText("No merged PRs in this window.", { exact: false }),
  ).toBeVisible();
  await expect(page.getByText("50.0%", { exact: true })).toHaveCount(0);
  await page.getByLabel("Work signal").selectOption("fix");
  await page
    .getByRole("combobox", { name: "Author", exact: true })
    .selectOption("test-engineer");
  await page
    .getByRole("combobox", { name: "Label", exact: true })
    .selectOption("bug");
  await page.getByLabel("Base branch").selectOption("master");
  await expect(page.getByText("50.0%", { exact: true })).toBeVisible();
  await page.getByLabel("Attribution").selectOption("tracked");
  await expect(page.getByText("Not enough comparable data")).toBeVisible();
  await page.getByLabel("Attribution").selectOption("all");
  await page.getByLabel("Compare with").selectOption("previous");
  await expect(page.getByText("Not enough comparable data")).toBeVisible();
  await page.getByLabel("Compare with").selectOption("six_months");
  await expect(page.getByText("50.0%", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.screenshot({
    path: "test-results/real-analytics-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/real-analytics-mobile.png",
    fullPage: true,
  });
  await page
    .getByRole("combobox", { name: "Repository", exact: true })
    .selectOption("Nasdin/superset");
  await expect(
    page.getByText("GitHub history has not been imported.", { exact: false }),
  ).toBeVisible();
  await expect(page.getByText("50.0%", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Repository scope")).toContainText(
    "Workflows always create issues, PRs and reports in Nasdin/superset",
  );
  await expect(
    page.getByRole("link", { name: "Open selected repository" }),
  ).toHaveAttribute("href", "https://github.com/Nasdin/superset");
  await page
    .getByRole("combobox", { name: "Repository", exact: true })
    .selectOption("apache/superset");
  await expect(
    page.getByRole("link", { name: "Open selected repository" }),
  ).toHaveAttribute("href", "https://github.com/apache/superset");
  await page.getByRole("button", { name: "Workflows", exact: true }).click();
  await expect(
    page.getByText("Nasdin/superset", { exact: true }),
  ).toBeVisible();
});

test("PR evidence filters and independent run artifacts are inspectable", async ({
  page,
}) => {
  const job = {
    id: "validator-test",
    kind: "validation",
    state: "review_ready",
    session_url: "https://app.devin.ai/sessions/validator-test",
    candidate_sha: "a".repeat(40),
    pr_number: 7,
    error: null,
    acu: 1,
    created: 1,
    updated: 1,
    started: 1,
    parent_id: "preparer-test",
    payload: { title: "chore: bump PyJWT", work_type: "dependency" },
    result: {
      summary: "Test fixture: independent validation",
      checks: [
        {
          name: "browser",
          passed: true,
          command: "test",
          detail: "Fixture check",
        },
      ],
      artifacts: [
        {
          kind: "screenshot",
          name: "Fixture screenshot",
          url: "https://attachments.devin.ai/test.png",
        },
      ],
    },
  };
  const rows = [
    {
      number: 7,
      title: "chore: bump PyJWT",
      author: "dependabot[bot]",
      category: "dependency",
      dependabot: true,
      state: "open",
      runs: [job],
      publications: [
        {
          key: "github:validator-test:7",
          state: "sent",
          url: "https://github.com/Nasdin/superset/pull/7#issuecomment-1",
        },
      ],
    },
    {
      number: 8,
      title: "feat: chart export",
      author: "test-engineer",
      category: "feature",
      dependabot: false,
      state: "open",
      runs: [],
      publications: [],
    },
    {
      number: 9,
      title: "fix: SQL rendering",
      author: "test-engineer",
      category: "fix",
      dependabot: false,
      state: "open",
      runs: [],
      publications: [],
    },
  ];
  await page.route("**/api/live/pull-requests?*", async (route) => {
    const q = new URL(route.request().url()).searchParams;
    const filtered = rows.filter(
      (r) =>
        (!q.get("kind") || r.category === q.get("kind")) &&
        (q.get("bot_only") !== "true" || r.dependabot) &&
        `${r.number} ${r.title} ${r.author}`
          .toLowerCase()
          .includes((q.get("search") || "").toLowerCase()),
    );
    await route.fulfill({
      json: {
        repository: "Nasdin/superset",
        branch: "cognition-release-6.1",
        enabled: true,
        sync: { last_success: "2026-09-20T00:00:00Z" },
        poll: {},
        total: filtered.length,
        rows: filtered,
        offset: 0,
        limit: 50,
      },
    });
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Dependabot runs", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "#7 chore: bump PyJWT" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "#8 feat: chart export" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "#7 chore: bump PyJWT" }).click();
  await expect(
    page.getByRole("link", { name: "Open evidence" }),
  ).toHaveAttribute("href", "https://attachments.devin.ai/test.png");
  await expect(
    page.getByRole("link", { name: "Published report" }),
  ).toHaveAttribute("href", /issuecomment-1$/);
  await expect(page.getByText("a".repeat(40), { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "PR evidence", exact: true }).click();
  await page.getByLabel("Change type").selectOption("feature");
  await expect(
    page.getByRole("button", { name: "#8 feat: chart export" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "#7 chore: bump PyJWT" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "#8 feat: chart export" }).click();
  await expect(
    page.getByText(
      "No Devin run or validation evidence has been recorded for this PR.",
    ),
  ).toBeVisible();
  await page.getByLabel("Change type").selectOption("fix");
  await expect(
    page.getByRole("button", { name: "#9 fix: SQL rendering" }),
  ).toBeVisible();
  await page.getByLabel("Find a PR").fill("not found");
  await expect(page.getByText("No PRs match these filters.")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});

test("learning page honestly reports empty history and workflow lanes", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Learning & memory", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Learning & memory", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("No completed observations yet.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("Not enough completed history", { exact: false }),
  ).toBeVisible();
  await page.getByLabel("Outcome", { exact: true }).selectOption("validated");
  await page.getByRole("button", { name: "Workflows", exact: true }).click();
  for (const name of [
    "Requested fixes",
    "Autonomous patches and fixes",
    "Dependency updates",
    "Integration & validation",
  ]) {
    await expect(
      page.getByRole("heading", { name, exact: true }),
    ).toBeVisible();
  }
});

test("learning source, memory snapshot and evidence remain linked", async ({
  page,
}) => {
  const job = {
    id: "learning-job",
    kind: "validation",
    state: "validation_failed",
    session_url: "https://app.devin.ai/sessions/test",
    candidate_sha: "a".repeat(40),
    pr_number: 8,
    error: "Missing browser evidence",
    acu: 1,
    created: 1789862400,
    updated: 1789862400,
    started: 1789862400,
    parent_id: null,
    payload: { title: "Fix date grain" },
    result: {
      summary: "Regression passed; browser was unavailable",
      checks: [],
      artifacts: [],
    },
  };
  await page.route("**/api/live/learning", (route) =>
    route.fulfill({
      json: {
        repository: "Nasdin/superset",
        branch: "cognition-release-6.1",
        sync: { state: "connected" },
        jobs: [job],
        lessons: [
          {
            id: "lesson-1",
            created: job.created,
            native_state: "confirmed",
            note_id: "note-1",
            observation: {
              job_id: job.id,
              kind: job.kind,
              status: job.state,
              title: job.payload.title,
              summary: job.result.summary,
              candidate_sha: job.candidate_sha,
              pr_number: 8,
            },
          },
        ],
        contexts: [
          {
            job_id: job.id,
            created: job.created,
            memories: [
              {
                lesson_id: "prior-lesson",
                knowledge_id: "note-previous",
                observation: { title: "Prior issue", status: "reported" },
              },
            ],
          },
        ],
        cohorts: [{ month: "2026-09", passed: 0, failed: 1 }],
      },
    }),
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "Learning & memory", exact: true })
    .click();
  await expect(page.getByText("0% (n=1)")).toBeVisible();
  await page.getByText("Inspect supplied memories").click();
  await expect(page.getByText("prior-lesson", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Inspect source & evidence" }).click();
  await expect(
    page.getByText("Missing browser evidence", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Outcome", { exact: true }).selectOption("validated");
  await expect(
    page.getByRole("button", { name: "Inspect source & evidence" }),
  ).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
