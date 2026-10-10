# CloneVoice — Frontend

Next.js 14 (App Router) · TypeScript strict · Tailwind CSS · TanStack Query · Axios.
Plan: [`../FRONTEND_IMPLEMENTATION_PLAN.md`](../FRONTEND_IMPLEMENTATION_PLAN.md).

## Local development

```bash
cp .env.example .env.local     # NEXT_PUBLIC_API_BASE_URL must end with /api/v1, no trailing slash
npm ci
npm run dev                    # http://localhost:3000
```

Run the backend on `http://localhost:8000` (same-site: the refresh cookie is scoped to the API host and
`ALLOWED_ORIGINS` already allows `http://localhost:3000`). For local accounts either set
`EMAIL_BACKEND=console` or `REQUIRE_EMAIL_VERIFICATION=false` in `backend/.env`.

The app fails fast at startup if `NEXT_PUBLIC_API_BASE_URL` is missing or malformed.

## Quality gates

| Command                | Purpose                                                            |
| ---------------------- | ------------------------------------------------------------------ |
| `npm run typecheck`    | `tsc --noEmit` (strict)                                            |
| `npm run lint`         | ESLint (no `console`, no `dangerouslySetInnerHTML`)                |
| `npm run format:check` | Prettier                                                           |
| `npm test`             | Vitest + React Testing Library + MSW (no live services)            |
| `npm run build`        | Production build (needs the env var above)                         |
| `npm run smoke`        | Release smoke test against a deployed web + API (see `RUNBOOK.md`) |
| `npm run perf`         | Lighthouse budgets on the public routes (see below)                |

## Routes

| Route                                                                                                | Who       | Purpose                                                   |
| ---------------------------------------------------------------------------------------------------- | --------- | --------------------------------------------------------- |
| `/`                                                                                                  | public    | Landing page                                              |
| `/login`, `/signup`, `/forgot-password`, `/reset-password`, `/verify-email`, `/auth/google/callback` | public    | Account entry and recovery                                |
| `/generate`                                                                                          | signed in | Pick a voice, enter text, generate and play/download      |
| `/voices`                                                                                            | signed in | Create a voice (upload or record), list and delete voices |
| `/history`                                                                                           | signed in | Past generations, replay and download                     |
| `/account`                                                                                           | signed in | Name, email verification, delete account                  |

`/dashboard` and `/profile` (the pre-redesign names) answer with a 308 to `/generate` and
`/voices`, and `?next=` values that still carry the old paths are mapped the same way
(`lib/auth/next-path.ts`), so old bookmarks and emailed links keep working.

## Design system and accessibility

- Colour, type, radius and motion are tokens (`app/globals.css`, `tailwind.config.ts`); components
  use token utilities only. `tests/theme.test.ts` fails on `dark:` variants, raw colours, ad-hoc
  durations and hand-rolled button/alert recipes, and asserts WCAG contrast for every token pair in
  light, dark and `prefers-contrast: more`.
- Buttons, alerts, badges, fields and the dialog live in `components/ui/`; new screens should use
  them rather than new class recipes.
- Targets are at least 44 px (the tab bar 56 px), checked by `e2e/responsive.spec.ts` at 320, 768
  and 1280 px, which also asserts no horizontal scroll and reflow at 400% zoom.
- Motion honours `prefers-reduced-motion`; the Upload/Record choice follows the radio keyboard model.
- Still manual: a screen-reader pass (NVDA, VoiceOver) over signup, create voice, generate,
  history and account.

## Performance budget

`npm run perf` audits `/`, `/login`, `/signup` and `/forgot-password` with Lighthouse's default
mobile profile (slow 4G, 4x CPU), takes the median of 3 runs (`PERF_RUNS`) and exits 1 if any route
exceeds: LCP 2500 ms, JS 200 KB transferred (gzipped), CLS 0.1, TBT 300 ms (measured CLS is about 0.001; the UX plan asks for 0.02). It needs a production
server (`npm run build && npx next start -p 3000`, or `PERF_BASE_URL`) and uses Playwright's
Chromium (or `CHROME_PATH`). Needs Node 22+ (Lighthouse's requirement). The pass/fail logic is
unit-tested in `tests/perf-budget.test.ts`; the budget itself lives in `perf/budget.mts`.

## Content-Security-Policy

`middleware.ts` sends a per-request, nonce-based CSP (`lib/csp.ts`); pages render dynamically so
Next.js can stamp the nonce on its scripts. It ships as **`Content-Security-Policy-Report-Only`**
so a bad directive cannot break the app: browse every flow with the console open, fix any
reported violation, then set the server env `CSP_ENFORCE=1` to enforce it.

## Error reporting and web vitals

Off by default. Set `NEXT_PUBLIC_SENTRY_DSN` at **build time** to enable it; the CSP then allows
the DSN's origin in `connect-src`. The SDK is imported lazily (never in the initial bundle) and
runs with no default integrations and no breadcrumbs. Every event passes `lib/observability/scrub.ts`,
an allow-list that drops user, request, URL query/fragment, extra data and local variables, and
redacts emails, JWTs and long tokens. Only server faults (5xx), error-boundary errors, uncaught
errors and non-"good" web vitals are sent.

## Layout

- `lib/errors.ts` — `ApiError` normalizer for every backend error shape (plan §5.5).
- `lib/api/http.ts` — Axios instance (`withCredentials`, timeouts, errors → `ApiError`).
- `lib/query.ts` — TanStack Query client; retries only idempotent GETs (R5).
- `mocks/` — MSW handlers for every endpoint; tests never hit a real API.

## Visual regression

`npm run test:visual` compares screenshots of every public and signed-in route (375, 768, 1280 and
1920 px, light and dark; the API is mocked, so no backend is needed) with the images in
`visual/__screenshots__`. Screenshots only match on the machine that made them, because fonts and
anti-aliasing differ per OS, so **the committed baselines come from CI, not from a laptop**:

1. Run the manual **visual-update** workflow (Actions tab, "Run workflow"). It regenerates the
   images on the same pinned runner and Node version as the `visual` job, runs the suite a second
   time to prove they are stable, and uploads them as the `visual-baselines` artifact. It never
   commits.
2. Download the artifact, **look at the images**, and replace `visual/__screenshots__` with them in
   a commit. A diff you did not expect is a regression, not something to accept.
3. Locally, `npm run test:visual` may report small font differences against CI baselines; that is
   expected. Use it to find real layout changes, and let CI decide. After the first reviewed CI
   baselines are committed, remove `continue-on-error` from the `visual` job in
   `.github/workflows/frontend.yml` so it gates merges.
