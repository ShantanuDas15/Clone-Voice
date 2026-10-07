/**
 * Release smoke test: `npm run smoke -- --web https://app.example.com --api https://api.example.com`
 * (see frontend/RUNBOOK.md). Read-only by default. `--with-account` additionally signs up a
 * throwaway user, checks the refresh cookie and refresh, then deletes the account again.
 * Needs Node 22.18+ (it runs TypeScript directly) and prints one line per check.
 */
import {
  type CheckResult,
  type Headers,
  checkCors,
  checkFragmentPageReferrer,
  checkMetricsProtected,
  checkRefreshCookie,
  checkSameSite,
  checkSecurityHeaders,
  exitCode,
} from "./lib.mts";

function arg(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

const web = (arg("web") ?? "").replace(/\/$/, "");
const apiOrigin = (arg("api") ?? "").replace(/\/$/, "");
const withAccount = process.argv.includes("--with-account");
if (!web || !apiOrigin) {
  console.error("usage: npm run smoke -- --web <web url> --api <api origin> [--with-account]");
  process.exit(2);
}
const apiBase = `${apiOrigin}/api/v1`;
const webOrigin = new URL(web).origin;
const results: CheckResult[] = [];
const add = (...r: CheckResult[]) => results.push(...r);
const pass = (name: string, detail: string): CheckResult => ({ name, level: "pass", detail });
const fail = (name: string, detail: string): CheckResult => ({ name, level: "fail", detail });

const headersOf = (res: Response): Headers => Object.fromEntries(res.headers.entries());

async function attempt(name: string, fn: () => Promise<void>): Promise<void> {
  try {
    await fn();
  } catch (error) {
    add(fail(name, `request failed: ${(error as Error).message}`));
  }
}

await attempt("web /login", async () => {
  const res = await fetch(`${web}/login`);
  add(
    res.status === 200
      ? pass("web /login responds", "200")
      : fail("web /login responds", `status ${res.status}`),
  );
  add(...checkSecurityHeaders(headersOf(res)));
});

await attempt("web /verify-email", async () => {
  const res = await fetch(`${web}/verify-email`);
  add(checkFragmentPageReferrer(headersOf(res)));
});

await attempt("api liveness", async () => {
  const res = await fetch(`${apiOrigin}/health/live`);
  add(
    res.status === 200
      ? pass("API /health/live", "200")
      : fail("API /health/live", `status ${res.status}`),
  );
});

await attempt("api readiness", async () => {
  const res = await fetch(`${apiOrigin}/health/ready`);
  add(
    res.status === 200
      ? pass("API /health/ready", "200 (database and models ready)")
      : { name: "API /health/ready", level: "warn", detail: `status ${res.status}: degraded` },
  );
});

await attempt("api terms", async () => {
  const res = await fetch(`${apiBase}/terms`, { headers: { Origin: webOrigin } });
  const body = (await res.json().catch(() => null)) as { version?: string } | null;
  add(
    res.status === 200 && body?.version
      ? pass("GET /terms", `version ${body.version}`)
      : fail("GET /terms", `status ${res.status}, no version`),
  );
  const pre = await fetch(`${apiBase}/auth/login`, {
    method: "OPTIONS",
    headers: {
      Origin: webOrigin,
      "Access-Control-Request-Method": "POST",
      "Access-Control-Request-Headers": "content-type,authorization",
    },
  });
  add(...checkCors(headersOf(pre), headersOf(res), webOrigin));
});

await attempt("metrics", async () => {
  const res = await fetch(`${apiOrigin}/metrics`);
  add(checkMetricsProtected(res.status));
});

add(checkSameSite(web, apiOrigin));

if (withAccount) {
  await attempt("account flow", async () => {
    const email = `smoke-${Date.now()}@example.com`;
    const password = `smoke-${Math.random().toString(36).slice(2)}-Aa1!`;
    const json = { "Content-Type": "application/json", Origin: webOrigin };
    const signup = await fetch(`${apiBase}/auth/signup`, {
      method: "POST",
      headers: json,
      body: JSON.stringify({ name: "Smoke Test", email, password }),
    });
    if (signup.status !== 201) {
      add(fail("signup", `status ${signup.status}`));
      return;
    }
    add(pass("signup", "201"));
    const token = ((await signup.json()) as { access_token?: string }).access_token ?? "";
    const setCookies = signup.headers.getSetCookie();
    add(...checkRefreshCookie(setCookies, apiOrigin.startsWith("https:")));
    const cookie = setCookies.map((c) => c.split(";")[0]).join("; ");
    const refresh = await fetch(`${apiBase}/auth/refresh`, {
      method: "POST",
      headers: { Origin: webOrigin, Cookie: cookie },
    });
    add(
      refresh.status === 200
        ? pass("refresh with the cookie", "200")
        : fail("refresh with the cookie", `status ${refresh.status}`),
    );
    // Clean up: delete the throwaway account (re-using the newest access token).
    const fresh = ((await refresh.json().catch(() => ({}))) as { access_token?: string })
      .access_token;
    const del = await fetch(`${apiBase}/auth/me`, {
      method: "DELETE",
      headers: { ...json, Authorization: `Bearer ${fresh ?? token}` },
      body: JSON.stringify({ password }),
    });
    add(
      del.status === 204
        ? pass("throwaway account deleted", "204")
        : fail("throwaway account deleted", `status ${del.status}: delete ${email} by hand`),
    );
  });
}

const mark = { pass: "ok  ", warn: "WARN", fail: "FAIL" } as const;
for (const r of results) console.log(`${mark[r.level]} ${r.name.padEnd(48)} ${r.detail}`);
const failed = results.filter((r) => r.level === "fail").length;
const warned = results.filter((r) => r.level === "warn").length;
console.log(`\n${results.length} checks: ${failed} failed, ${warned} warnings`);
process.exit(exitCode(results));
