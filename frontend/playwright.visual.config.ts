import { defineConfig, devices } from "@playwright/test";

/**
 * Visual-regression baselines (plan U7.2). The API is mocked at the network layer, so no backend
 * is needed. Baselines are committed under `visual/__screenshots__`; regenerate them on purpose
 * with `npm run test:visual -- --update-snapshots` and review the diff by eye.
 */
export default defineConfig({
  testDir: "./visual",
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}{ext}",
  timeout: 60_000,
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.002, animations: "disabled" } },
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3000",
    ...devices["Desktop Chrome"],
    reducedMotion: "reduce",
    locale: "en-US",
    timezoneId: "UTC",
  },
  projects: [
    { name: "chromium", testIgnore: /cross-browser/ },
    // Screenshots differ per engine, so the other engines run only the structural smoke spec.
    { name: "webkit", testMatch: /cross-browser/, use: devices["Desktop Safari"] },
    { name: "firefox", testMatch: /cross-browser/, use: devices["Desktop Firefox"] },
  ],
  webServer: {
    command:
      "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1 npm run build && npx next start -p 3000",
    url: "http://localhost:3000",
    reuseExistingServer: true,
    timeout: 300_000,
  },
});
