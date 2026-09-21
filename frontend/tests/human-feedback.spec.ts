import { test, expect } from "@playwright/test";
import type { LearningData } from "../src/learningTypes";

test("operator correction can be saved, revised and retired without losing attribution", async ({
  page,
}) => {
  const run = {
    id: "run-1",
    kind: "validation",
    state: "validation_failed",
    payload: { title: "JWT security regression" },
    session_url: "https://app.devin.ai/sessions/test",
    candidate_sha: "a".repeat(40),
    pr_number: 6,
    acu: 1,
    created: 1789988000,
    updated: 1789988000,
    started: 1789988000,
    parent_id: null,
    error: null,
  };
  const data: LearningData = {
    repository: "Nasdin/superset",
    branch: "demo",
    sync: { state: "connected" },
    jobs: [run],
    lessons: [],
    contexts: [],
    cohorts: [{ month: "2026-09", passed: 2, failed: 1 }],
  };
  await page.route("**/api/live/learning", (r) => r.fulfill({ json: data }));
  await page.route("**/api/live/operator", (r) =>
    r.fulfill({ json: { authenticated: true } }),
  );
  const requests: Record<string, unknown>[] = [];
  await page.route("**/api/live/learning/feedback", async (r) => {
    const body = r.request().postDataJSON();
    requests.push(body);
    expect(r.request().headers().authorization).toBe("Bearer test-operator");
    data.lessons.forEach((l) => (l.is_current = false));
    data.lessons.unshift({
      id: body.request_id,
      is_current: true,
      created: 1789988000 + requests.length,
      native_state: "pending",
      note_id: null,
      observation: {
        job_id: run.id,
        kind: "human_feedback",
        status: body.retired ? "retired" : "corrected",
        title: body.title,
        summary: body.correction,
        candidate_sha: run.candidate_sha,
        pr_number: 6,
        session_url: run.session_url,
        feedback_id: body.feedback_id || body.request_id,
        previous_revision: body.expected_revision,
        author: body.author,
        original_author: "Nasrudin via Codex",
        reason: body.reason,
      },
    });
    await r.fulfill({
      json: {
        id: body.request_id,
        feedback_id: body.feedback_id || body.request_id,
      },
    });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/#learning");
  await page
    .getByRole("button", { name: "Give feedback", exact: true })
    .click();
  const editor = page.getByRole("form", { name: "Memory editor" });
  await expect(
    editor.getByRole("button", { name: "Save correction" }),
  ).toBeDisabled();
  await page.getByText("Execution access", { exact: true }).click();
  await page.getByLabel("Operator key", { exact: true }).fill("test-operator");
  await page.getByRole("button", { name: "Unlock execution controls" }).click();
  await editor
    .getByLabel("Your name", { exact: true })
    .fill("Nasrudin via Codex");
  await editor.getByLabel("Source run", { exact: true }).selectOption(run.id);
  await editor
    .getByLabel("Memory title", { exact: true })
    .fill("A failing regression cannot be reported passed");
  await editor
    .getByLabel("Why are you correcting this?", { exact: true })
    .fill("The summary contradicted the actual failing test count.");
  await editor
    .getByLabel("What should Devin remember?", { exact: true })
    .fill(
      "Report actual counts and keep the gate failed until the failing test is fixed.",
    );
  await editor.getByRole("button", { name: "Save correction" }).click();
  const detail = page.getByRole("region", { name: "Feedback details" });
  await expect(
    detail
      .locator(".feedback-guidance")
      .getByText(
        "Report actual counts and keep the gate failed until the failing test is fixed.",
      ),
  ).toBeVisible();
  await expect(
    detail.getByText("Devin Knowledge · pending", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/human-feedback-desktop.png",
    fullPage: true,
  });
  await detail.getByRole("button", { name: "Edit memory" }).click();
  await editor.getByLabel("Your name", { exact: true }).fill("Reviewer two");
  await editor
    .getByLabel("Why are you correcting this?", { exact: true })
    .fill("Clarify baseline failures must remain visible too.");
  await editor
    .getByLabel("What should Devin remember?", { exact: true })
    .fill(
      "Preserve failures even when reproduced on the baseline. Do not call the PR ready.",
    );
  await editor.getByRole("button", { name: "Save revision" }).click();
  await expect(
    detail
      .locator(".feedback-guidance")
      .getByText(
        "Preserve failures even when reproduced on the baseline. Do not call the PR ready.",
      ),
  ).toBeVisible();
  await detail.getByText("Revision history · 2", { exact: true }).click();
  await expect(
    detail.getByText(
      "Report actual counts and keep the gate failed until the failing test is fixed.",
    ),
  ).toBeVisible();
  expect(requests[1].expected_revision).toBe(requests[0].request_id);
  expect(requests[1].feedback_id).toBe(requests[0].request_id);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/human-feedback-mobile.png",
    fullPage: true,
  });
  await detail.getByRole("button", { name: "Edit memory" }).click();
  await editor.getByLabel("Your name", { exact: true }).fill("Reviewer two");
  await editor
    .getByLabel("Why are you correcting this?", { exact: true })
    .fill("Retire this lesson for the demo.");
  await editor.getByLabel("Retire this memory from future runs").check();
  await editor.getByRole("button", { name: "Save revision" }).click();
  await expect(
    page
      .getByRole("region", { name: "Feedback journal" })
      .getByText("retired", { exact: true }),
  ).toBeVisible();
  expect(requests[2].retired).toBe(true);
});
