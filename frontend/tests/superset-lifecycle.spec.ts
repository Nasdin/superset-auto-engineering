import { expect, test, type Page } from "@playwright/test";

// Synthetic iframe exercises the actual SDK channel/lifecycle. Real chart query
// correctness is covered separately by the provisioned Superset integration test.
const frame = `<!doctype html><title>Synthetic SDK responder</title><script>
addEventListener('message', event => {
 const port = event.ports[0]; if (!port) return;
 port.onmessage = ({data}) => {
  if (data.switchboardAction === 'get') port.postMessage({
   switchboardAction: 'reply', messageId: data.messageId,
   result: {height: 900, width: 1000}
  });
 }; port.start();
});</script>`;

async function sessions(page: Page, failRefresh = false) {
  let calls = 0;
  await page.route("**/api/analytics/superset/session?**", async (route) => {
    calls += 1;
    if (failRefresh && calls === 2) {
      await route.fulfill({ status: 502, json: { detail: "BI unavailable" } });
      return;
    }
    const origin = new URL(route.request().url()).origin;
    const params = new URL(route.request().url()).searchParams;
    const payload = Buffer.from(
      JSON.stringify({ exp: Date.now() / 1000 + 10 }),
    ).toString("base64url");
    await route.fulfill({
      json: {
        dashboard_id:
          (params.get("layout") === "mobile" ? "mobile-" : "") +
          (params.get("cadence") === "rolling" ? "rolling" : "monthly"),
        superset_url: `${origin}/synthetic-bi`,
        token: `e30.${payload}.signature`,
      },
    });
  });
  return () => calls;
}

test("unresponsive Superset shell fails visibly and can be reopened", async ({
  page,
}) => {
  await page.clock.install();
  await sessions(page);
  let responsive = false;
  await page.route("**/synthetic-bi/embedded/**", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: responsive ? frame : "<p>BI unavailable</p>",
    }),
  );
  await page.goto("/#analytics");
  await expect(page.locator(".superset-panel iframe")).toHaveCount(1);
  await page.clock.fastForward(46_000);
  await expect(page.getByRole("alert")).toContainText(
    "Superset did not respond in time",
  );
  await expect(page.locator(".superset-panel iframe")).toHaveCount(0);
  responsive = true;
  await page.getByRole("button", { name: "Retry Superset" }).click();
  await expect(page.locator(".superset-panel iframe")).toHaveAttribute(
    "title",
    "Superset engineering impact charts",
  );
  await expect(page.getByText("Opening the Superset dashboard…")).toHaveCount(
    0,
  );
  await expect(page.locator(".superset-panel iframe")).toHaveCSS(
    "height",
    "900px",
  );
});

test("narrow viewports select native full-width Superset layouts for both cadences", async ({
  page,
}) => {
  await sessions(page);
  await page.route("**/synthetic-bi/embedded/**", (route) =>
    route.fulfill({ contentType: "text/html", body: frame }),
  );
  await page.goto("/#analytics");
  const iframe = page.locator(".superset-panel iframe");
  await expect(iframe).toHaveAttribute("src", /\/embedded\/monthly\?/);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(iframe).toHaveAttribute("src", /\/embedded\/mobile-monthly\?/);
  await page
    .getByRole("button", { name: "Rolling window", exact: true })
    .click();
  await expect(iframe).toHaveAttribute("src", /\/embedded\/mobile-rolling\?/);
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(iframe).toHaveAttribute("src", /\/embedded\/rolling\?/);
  await expect(iframe).toHaveCount(1);
});

test("SDK renewal failure is visible, recovers and stops on navigation", async ({
  page,
}) => {
  await page.clock.install();
  const count = await sessions(page, true);
  await page.route("**/synthetic-bi/embedded/**", (route) =>
    route.fulfill({ contentType: "text/html", body: frame }),
  );
  await page.goto("/#analytics");
  await expect(page.locator(".superset-panel iframe")).toHaveCSS(
    "height",
    "900px",
  );
  await page.clock.fastForward(6000);
  await expect(
    page.getByText(/Superset access could not be renewed/),
  ).toBeVisible();
  await page.clock.fastForward(11_000);
  await expect(
    page.getByText(/Superset access could not be renewed/),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Workflows", exact: true }).click();
  const before = count();
  await page.clock.fastForward(60_000);
  expect(count()).toBe(before);
  await expect(page.locator(".superset-panel iframe")).toHaveCount(0);
});

test("changing cadence during initialization keeps exactly the new frame", async ({
  page,
}) => {
  await sessions(page);
  let release: () => void = () => {};
  const blocked = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/synthetic-bi/embedded/**", async (route) => {
    if (route.request().url().includes("monthly")) await blocked;
    await route
      .fulfill({ contentType: "text/html", body: frame })
      .catch(() => {});
  });
  await page.goto("/#analytics");
  await expect(page.locator(".superset-panel iframe")).toHaveAttribute(
    "src",
    /monthly/,
  );
  await page
    .getByRole("button", { name: "Rolling window", exact: true })
    .click();
  await expect(page.locator(".superset-panel iframe")).toHaveAttribute(
    "src",
    /rolling/,
  );
  await expect(page.locator(".superset-panel iframe")).toHaveCSS(
    "height",
    "900px",
  );
  release();
  await expect(page.locator(".superset-panel iframe")).toHaveCount(1);
  await expect(page.locator(".superset-panel iframe")).toHaveAttribute(
    "src",
    /rolling/,
  );
});
