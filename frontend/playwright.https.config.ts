import { defineConfig, devices } from "@playwright/test";

import base from "./playwright.config";

/**
 * WebKit over local HTTPS (it drops the API's `Secure` refresh cookie on plain HTTP). The stack is
 * started by hand behind `e2e/tools/https-proxy.mjs`; see e2e/README.md.
 */
export default defineConfig({
  ...base,
  use: { ...base.use, baseURL: "https://localhost:3443", ignoreHTTPSErrors: true },
  projects: [{ name: "webkit", use: { ...devices["Desktop Safari"], ignoreHTTPSErrors: true } }],
  webServer: undefined,
});
