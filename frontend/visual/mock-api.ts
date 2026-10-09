import type { Page } from "@playwright/test";

/** Network-layer mock of the API for the visual and cross-browser specs (no backend needed). */
export const ORIGIN = "http://localhost:3000";
const CORS = {
  "Access-Control-Allow-Origin": ORIGIN,
  "Access-Control-Allow-Credentials": "true",
  "Access-Control-Allow-Headers": "*",
  "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
  "Access-Control-Expose-Headers": "X-Total-Count",
};

const user = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "ada@example.com",
  name: "Ada",
  avatar_url: null,
  provider: "local",
  has_password: true,
  email_verified_at: "2026-10-01T00:00:00Z",
  created_at: "2026-10-01T00:00:00Z",
};
const voice = (id: string, name: string, status: string) => ({
  id,
  name,
  status,
  consent_confirmed_at: "2026-10-01T00:00:00Z",
  terms_version: "1",
  created_at: "2026-10-01T00:00:00Z",
});
const voices = [
  voice("22222222-2222-4222-8222-222222222222", "My voice", "ready"),
  voice("44444444-4444-4444-8444-444444444444", "Broken sample", "failed"),
];
const generation = {
  id: "33333333-3333-4333-8333-333333333333",
  voice_profile_id: "22222222-2222-4222-8222-222222222222",
  voice_profile_name: "My voice",
  status: "completed",
  input_text: "Hello there.",
  output_filename: "synthesized_33333333.wav",
  duration_seconds: 1.5,
  audio_available: true,
  created_at: "2026-10-02T00:00:00Z",
};

/** Mock a signed-in session; `unverified` + no voices gives the first-run state of /generate. */
export async function mockApi(page: Page, firstRun: boolean): Promise<void> {
  const body = (data: unknown, extra: Record<string, string> = {}) => ({
    status: 200,
    contentType: "application/json",
    headers: { ...CORS, ...extra },
    body: JSON.stringify(data),
  });
  await page.route("**/health**", (r) => r.fulfill(body({ status: "ok" })));
  await page.route("**/api/v1/**", (r) => {
    const req = r.request();
    if (req.method() === "OPTIONS") return r.fulfill({ status: 204, headers: CORS });
    const path = new URL(req.url()).pathname.replace("/api/v1", "");
    if (path === "/auth/refresh")
      return r.fulfill(body({ access_token: "t", token_type: "bearer" }));
    if (path === "/auth/me")
      return r.fulfill(body(firstRun ? { ...user, email_verified_at: null } : user));
    if (path === "/voice/profiles") return r.fulfill(body(firstRun ? [] : voices));
    if (path === "/synthesize/history")
      return r.fulfill(
        body(firstRun ? [] : [generation], { "X-Total-Count": firstRun ? "0" : "1" }),
      );
    if (path === "/terms") return r.fulfill(body({ version: "1", url: null }));
    return r.fulfill({ status: 404, headers: CORS, body: "{}" });
  });
}

/** Mock a signed-out visitor: health is ok and every API call answers 401. */
export async function mockSignedOut(page: Page): Promise<void> {
  await page.route("**/health**", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      headers: CORS,
      body: '{"status":"ok"}',
    }),
  );
  await page.route("**/api/v1/**", (r) =>
    r.request().method() === "OPTIONS"
      ? r.fulfill({ status: 204, headers: CORS })
      : r.fulfill({ status: 401, contentType: "application/json", headers: CORS, body: "{}" }),
  );
}
