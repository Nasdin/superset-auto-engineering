import { defineConfig } from "@playwright/test";
const external = process.env.E2E_BASE_URL;
export default defineConfig({
  testDir: "tests",
  // Browser tests share one constrained API process and ledger. Backend tests
  // exercise concurrent overload separately; UI scenarios run deterministically.
  workers: 1,
  use: {
    baseURL: external || "http://127.0.0.1:8010",
    browserName: "chromium",
    trace: "retain-on-failure",
  },
  webServer: external
    ? undefined
    : {
        command: `${process.env.TEST_PYTHON || "../backend/.venv/bin/python"} ../scripts/serve_test_app.py`,
        url: "http://127.0.0.1:8010/api/health",
        reuseExistingServer: false,
        timeout: 30_000,
      },
  reporter: "list",
});
