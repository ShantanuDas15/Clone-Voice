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

| Command                | Purpose                                                 |
| ---------------------- | ------------------------------------------------------- |
| `npm run typecheck`    | `tsc --noEmit` (strict)                                 |
| `npm run lint`         | ESLint (no `console`, no `dangerouslySetInnerHTML`)     |
| `npm run format:check` | Prettier                                                |
| `npm test`             | Vitest + React Testing Library + MSW (no live services) |
| `npm run build`        | Production build (needs the env var above)              |

## Content-Security-Policy

`middleware.ts` sends a per-request, nonce-based CSP (`lib/csp.ts`); pages render dynamically so
Next.js can stamp the nonce on its scripts. It ships as **`Content-Security-Policy-Report-Only`**
so a bad directive cannot break the app: browse every flow with the console open, fix any
reported violation, then set the server env `CSP_ENFORCE=1` to enforce it.

## Layout

- `lib/errors.ts` — `ApiError` normalizer for every backend error shape (plan §5.5).
- `lib/api/http.ts` — Axios instance (`withCredentials`, timeouts, errors → `ApiError`).
- `lib/query.ts` — TanStack Query client; retries only idempotent GETs (R5).
- `mocks/` — MSW handlers for every endpoint; tests never hit a real API.
