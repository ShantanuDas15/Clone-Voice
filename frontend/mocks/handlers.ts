import { HttpResponse, http } from "msw";

const API = "http://api.test/api/v1";
const ORIGIN = "http://api.test";

export const fixtures = {
  user: {
    id: "11111111-1111-4111-8111-111111111111",
    email: "ada@example.com",
    name: "Ada",
    avatar_url: null,
    provider: "local",
    has_password: true,
    email_verified_at: "2026-10-01T00:00:00Z",
    created_at: "2026-10-01T00:00:00Z",
  },
  profile: {
    id: "22222222-2222-4222-8222-222222222222",
    name: "My voice",
    status: "ready",
    consent_confirmed_at: "2026-10-01T00:00:00Z",
    terms_version: "1",
    created_at: "2026-10-01T00:00:00Z",
  },
  generation: {
    id: "33333333-3333-4333-8333-333333333333",
    voice_profile_id: "22222222-2222-4222-8222-222222222222",
    voice_profile_name: "My voice",
    status: "completed",
    input_text: "Hello there.",
    output_filename: "synthesized_33333333.wav",
    duration_seconds: 1.5,
    audio_available: true,
    created_at: "2026-10-02T00:00:00Z",
  },
  token: { access_token: "test-access-token", token_type: "bearer" },
} as const;

/** Default happy-path handlers for every endpoint in plan §3; tests override per case. */
export const handlers = [
  http.get(`${ORIGIN}/health/ready`, () => HttpResponse.json({ status: "ok" })),
  http.get(`${API}/terms`, () => HttpResponse.json({ version: "1", url: null })),
  http.post(`${API}/auth/signup`, () => HttpResponse.json(fixtures.token, { status: 201 })),
  http.post(`${API}/auth/login`, () => HttpResponse.json(fixtures.token)),
  http.post(`${API}/auth/refresh`, () => HttpResponse.json(fixtures.token)),
  http.post(`${API}/auth/logout`, () => new HttpResponse(null, { status: 204 })),
  http.get(`${API}/auth/me`, () => HttpResponse.json(fixtures.user)),
  http.patch(`${API}/auth/me`, () => HttpResponse.json(fixtures.user)),
  http.delete(`${API}/auth/me`, () => new HttpResponse(null, { status: 204 })),
  http.post(`${API}/auth/verify-email`, () => HttpResponse.json({ detail: "Email verified" })),
  http.post(`${API}/auth/resend-verification`, () =>
    HttpResponse.json({ detail: "Verification email sent" }, { status: 202 }),
  ),
  http.post(`${API}/auth/forgot-password`, () =>
    HttpResponse.json(
      { detail: "If that address has an account, a reset link has been sent" },
      { status: 202 },
    ),
  ),
  http.post(`${API}/auth/reset-password`, () => HttpResponse.json({ detail: "Password updated" })),
  http.get(`${API}/voice/profiles`, () => HttpResponse.json([fixtures.profile])),
  http.post(`${API}/voice/upload`, () => HttpResponse.json(fixtures.profile, { status: 201 })),
  http.delete(`${API}/voice/profiles/:id`, () => HttpResponse.json({ status: "deleted" })),
  http.post(
    `${API}/synthesize`,
    () =>
      new HttpResponse(new Uint8Array([82, 73, 70, 70]), {
        headers: { "Content-Type": "audio/wav" },
      }),
  ),
  http.get(`${API}/synthesize/history`, () =>
    HttpResponse.json([fixtures.generation], { headers: { "X-Total-Count": "1" } }),
  ),
  http.get(
    `${API}/synthesize/:id/audio`,
    () =>
      new HttpResponse(new Uint8Array([82, 73, 70, 70]), {
        headers: { "Content-Type": "audio/wav" },
      }),
  ),
];
