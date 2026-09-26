import { defineConfig } from "@playwright/test";

/**
 * E16-03 demo smoke test (+ E16-04 backup recording via npm run e2e:record, which saves a video).
 *   npm run e2e            # reuses `npm run dev` if it is already running
 *   npm run e2e:record     # same, headed, video kept for the backup recording
 * Uses the installed Google Chrome, so no browser download is needed.
 */
export default defineConfig({
  testDir: ".",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", { open: "never", outputFolder: "report" }]],
  outputDir: "results",
  use: {
    baseURL: "http://localhost:5173",
    channel: "chrome",
    viewport: { width: 1600, height: 900 },
    locale: "th-TH",
    // Video only for the backup recording (npm run e2e:record) — needs `npx playwright install ffmpeg`.
    video: process.env.E2E_SLOW ? { mode: "on", size: { width: 1600, height: 900 } } : "off",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev",
    cwd: "..",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
