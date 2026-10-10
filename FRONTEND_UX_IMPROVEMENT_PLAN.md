# CloneVoice — Frontend Design, UI & UX Improvement Plan

> **Status:** Planning document, now with owner decisions (§11, 2026-10-08) and the U0 implemented in two slices: brand mark, palette tokens, fonts and the theme toggle (FE-UX0), then the Button/Alert/Badge primitives (FE-UX1) and the Input/Select/Textarea field primitives (FE-UX2) (commits recorded in `FRONTEND_IMPLEMENTATION_PLAN.md` > Task Status Log). Remaining in U0: U0.6 and the visual-regression baseline; `Card` is deferred to U3/U4. U1 is done (FE-UX3: `NavLink`, the route split to `/generate`, `/voices`, `/history`, `/account` with 308 redirects, `next=` mapping; FE-UX4: mobile tab bar, one inline verification alert, two-column layouts). U2 is done (FE-UX5: U2.3 first-run checklist with the blocked-Generate reason, U2.4 voice CTA; FE-UX6: U2.1 landing, U2.2 auth polish, U2.6 copy; FE-UX7: U2.5 progress and result actions, U2.7 file drop zone), including the Google provider mark (FE-UX22). U3 is done (FE-UX8: U3.1 `Dialog`, the session-ended message of U3.2; FE-UX9: U3.3 offline, U3.4 error recovery, U3.5 empty states) including the draft restore of U3.2 (FE-UX24). U4 is done (FE-UX10: U4.1 waveform, U4.3 `Take`, U4.4 placement; FE-UX11: U4.2 live level meter). U5 is done (FE-UX12), except toast/disclosure motion (see the status log). U6 is mostly done (FE-UX13: U6.1 radio keyboard model; FE-UX14: U6.2 `prefers-contrast: more` tokens and the forced-colors pass, U6.5 touch targets and 320 px reflow measured in a browser). FE-UX15 confirmed the U6.4 performance budgets. Remaining in U6: U6.3 manual screen-reader pass (needs a person). U7 is started: FE-UX16 did U7.3 (`frontend/README.md` routes and design-system sections, RUNBOOK note on the legacy redirects); FE-UX17 ran U7.1 (the full e2e on Chromium and Firefox for the first time since the redesign) and fixed what it found; U7.2 is done (FE-UX18 public, FE-UX19 signed-in) and U7.4 is done (FE-UX20); only the §9 release gate and the owner decisions remain.
> **Produced:** 2026-10-08 by following `frontend-ux-improvement-prompt.md`.
> **Citation convention:** `path:line` = file opened this session (paths relative to `frontend/` unless stated).
> `shot:<name>` = a screenshot captured this session (scratchpad, not committed). `Proposal:` = not in the repo. `Assumption:` = not verified.
> Severity: **Critical** (blocks the core journey), **High** (a new user is likely to fail or leave), **Medium** (friction or a standards gap), **Low** (polish).

---

## 1. Coverage note

**Status: COMPLETE for the primary journeys; PARTIAL for secondary screens.**

### Reviewed (opened and read)
| Area | Files |
|---|---|
| Tokens, theme, config | `app/globals.css`, `tailwind.config.ts`, `package.json` (dependencies), `app/layout.tsx` |
| Shell and navigation | `components/app-shell.tsx`, `components/user-menu.tsx`, `components/degraded-banner.tsx`, `components/verification-banner.tsx`, `components/providers.tsx`, `components/auth-gate.tsx`, `app/(app)/layout.tsx` |
| Pages | `app/page.tsx`, `app/(public)/signup/page.tsx`, `app/(public)/login/page.tsx`, `app/(app)/dashboard/page.tsx`, `app/(app)/profile/page.tsx`, `app/global-error.tsx` |
| Components | `signup-form`, `login-form`, `form-fields`, `google-button`, `text-to-speech-form`, `voice-profile-select`, `upload-voice-form`, `audio-player`, `audio-uploader`, `recorder`, `voice-profile-list`, `history-list`, `error-fallback`, `resend-verification` (partial: lines 1-60), `verify-email-view` (class and copy lines only), `account-section` (class lines only) |
| Support | `lib/draft.ts`; `lib/recording.ts` (constants only); `lib/errors.ts` (kind table lines only) |
| Product docs | `project_description.md` (lines 1-50, repo root), `FRONTEND_IMPLEMENTATION_PLAN.md` (status log, read earlier this session) |

### Rendered (screenshots captured)
Chromium (Playwright) against a production build (`next start`) with the API **mocked at the network layer** (no real backend, no real audio). Five screens (`/`, `/signup`, `/login`, `/dashboard`, `/profile`) × two widths (375 px, 1280 px) × light and dark = 20 images. The signed-in screens used a mocked unverified user, one ready and one failed voice, and one history row. **Viewed** (opened and inspected): `home-d-light`, `dashboard-d-dark`, `profile-m-light`. **Captured but not individually inspected:** the other 17; any visual claim about them is code-derived and marked Inferred.

### Not reviewed (nothing is claimed about them)
`app/(public)/forgot-password`, `reset-password`, `verify-email` pages and their forms; `app/auth/callback`; `components/google-callback`, `reset-password-form`, `forgot-password-form`; `hooks/*` (except by name); `lib/api/*`, `lib/auth/*`, `lib/validation/*`; `e2e/*` and `tests/*`; `lib/csp.ts` and `middleware.ts` (only known from the earlier plan); real audio playback, the real recording flow, and any state that needs a live backend (a successful generation, a mid-upload progress bar, the delete dialog open). Those states are **code-read only**.

### Method limits
- A full-page screenshot of a page with a `sticky bottom-0` element (`components/verification-banner.tsx:11`) places that element mid-image; **that is a capture artefact, not a finding.** I did not count it.
- Contrast ratios in this document were computed from the token values (WCAG 2.x relative luminance), not measured on rendered pixels.

---

## 2. Executive summary

The frontend is **functionally mature and visually unfinished**. Every resilience rule from the engineering plan is implemented (cooldowns, abort, error boundaries, health banner, consent), but the visual layer is a raw Tailwind baseline: eight colour tokens (`app/globals.css:5-15`), the browser's default font, one repeated button recipe, and no component primitives. There is also no AI-template look to remove: no gradients, glows, shadows, uppercase labels or entrance animations exist (grep of `app/` and `components/` found none). The interface is plain rather than generic.

**Top 3 problems for a new user**
1. **The first minute dead-ends.** After signup the user lands on a Dashboard whose only control, the voice picker, is empty (`components/signup-form.tsx:44`, `components/voice-profile-select.tsx:43-50`). To get a first result they must find "Create one", cross to a page titled "Your account" that holds four unrelated jobs (`app/(app)/profile/page.tsx:13-36`), create a voice, then navigate back. Nothing links the finished voice to the next step (`components/upload-voice-form.tsx:257-261`).
2. **The email-verification gate is announced in several places and enforced late.** An unverified user sees a notice on the generate form and a sticky banner at once (`shot:dashboard-d-dark`), and the same notice again on the upload form, yet the Generate button stays enabled and only fails after submit (`components/text-to-speech-form.tsx:212`).
3. **The landing page does not earn trust.** A headline, one sentence and one button on a mostly blank page (`app/page.tsx:5-16`, `shot:home-d-light`), for a product whose central question is "is it safe to give this my voice?".

**Top 3 risks of breakdown**
1. Form-control borders measure about 1.3:1 against the page, far under the 3:1 WCAG 1.4.11 asks of input boundaries (`app/globals.css:10`, `components/form-fields.tsx:24`): controls can disappear for low-vision users and in bright light.
2. Interaction states are missing: no hover, active or `focus-visible` styling anywhere (only the skip link), and "disabled" is `opacity-60` alone, so a keyboard user's position and a button's availability are not reliably legible.
3. Destructive actions look like constructive ones (the confirm-delete button is the primary colour, `components/voice-profile-list.tsx:54`), inside an inline "dialog" with no overlay.

**Recommendation:** keep the stack (Next.js, Tailwind, TanStack Query, no component library) and add a **small token and primitive layer**, then fix information architecture and the first-run path *before* any decoration. Spend the visual effort in one place: a shared **voice-take** component (waveform, timecode, level meter) used by the recorder, the result player and history. Eight phases, ordered by dependency and risk (§7).

---

## 3. Findings table

IDs are referenced by §7 and §8. "Observed" = seen in code or a viewed screenshot this session. "Inferred" = derived from code without a rendered check.

| ID | Area | Issue | Evidence | Severity | Obs/Inf |
|---|---|---|---|---|---|
| UX-01 | Design tokens | Only 8 colour tokens; no semantic `danger`/`success`/`accent`; errors hardcode `text-red-600 dark:text-red-400` | `app/globals.css:5-15`; `tailwind.config.ts:8-18`; the string appears in 9 component files (`components/form-fields.tsx:31`, `login-form.tsx:61,81`, `signup-form.tsx:97`) | **Medium**: every colour change touches 9+ files and success/danger have no shared look | Observed |
| UX-02 | Typography | No font and no type scale; the page renders the OS default sans | `tailwind.config.ts:6-20` (no `fontFamily`); `app/layout.tsx:1-27` (no `next/font`); `shot:home-d-light` | **Medium**: nothing says "audio product"; headings differ only by Tailwind size classes | Observed |
| UX-03 | Contrast | Control and card borders are 1.33:1 (light) and 1.53:1 (dark) against the background | `app/globals.css:10,23`; used for inputs at `components/form-fields.tsx:24`, `text-to-speech-form.tsx:167`, `voice-profile-select.tsx:29`; computed from token values | **High**: fails WCAG 1.4.11 (3:1) for input boundaries; inputs are hard to find | Observed (computed) |
| UX-04 | First impression | Landing page is one headline, one sentence and one button; no explanation of how it works, no consent/safety statement, no example output | `app/page.tsx:5-16`; `shot:home-d-light` (about 60% of the viewport is blank) | **High**: a voice-cloning product must establish trust before asking for an account | Observed |
| UX-05 | Information architecture | Nav says "Dashboard" and "Account", but `/profile` is the place to create voices, list voices, read history and delete the account; its tab title is "Your account" and its H1 is "Create a voice" | `components/user-menu.tsx:39-44`; `app/(app)/profile/page.tsx:8,13-36`; `app/(app)/dashboard/page.tsx:13-16` | **High**: the main setup action lives under a label that does not name it; one long scroll mixes four jobs | Observed |
| UX-06 | First-run | New user lands on the generator with an empty picker; the "Create one" link is a plain `<a href>` (full reload); after a voice is created only a text line appears, with no "Generate with this voice" action | `components/signup-form.tsx:44`; `components/voice-profile-select.tsx:43-50`; `components/upload-voice-form.tsx:257-261`; the only forward link is far below the list at `components/voice-profile-list.tsx:108-113` | **High**: time to first voice output includes a detour with no signposting | Observed |
| UX-07 | Verification gate | Unverified users get the same notice in up to three places (two at once on the dashboard), and Generate/Create stay enabled until a 403 | `components/text-to-speech-form.tsx:147-151,212`; `components/upload-voice-form.tsx:144-148,267-270`; `components/verification-banner.tsx:11-14`; `shot:dashboard-d-dark` (two notices visible at once) | **High**: the first real action fails after effort; the copy repeats | Observed |
| UX-08 | Generate feedback | Progress is a text counter ("Generating… 12 s"); no visual progress and no post-result actions such as "Edit text" or "Generate again" | `components/text-to-speech-form.tsx:187-192,229-244` | **Medium**: the product's central wait feels stalled; the result is a dead end | Observed (code) |
| UX-09 | Interaction states | No hover, active or `focus-visible` styles on buttons, links or inputs; disabled is `opacity-60` only; focus relies on the browser default ring | grep for `focus`/`hover:` across `app/` and `components/`: only the skip link (`components/app-shell.tsx:14`) and `hover:underline` at `components/user-menu.tsx:27,39,42`; `text-to-speech-form.tsx:213` | **Medium**: states G of the audit are mostly absent; a washed-out "Save name" button (`shot:profile-m-light`) reads as unfinished, not unavailable | Observed grep; focus ring Inferred |
| UX-10 | Components | No Button, Alert, Card or Badge primitive: the primary-button recipe is repeated 8 times across 6 files; only `TextField` is shared | grep `min-h-11 rounded bg-primary` → 8 occurrences in 6 files; `components/form-fields.tsx:9` | **Medium**: inconsistency risk and the cost of every restyle | Observed |
| UX-11 | Generic-look check | Accent is a stock indigo (`243 75% 50%`) chosen for no product reason; otherwise **no AI tells found** (no gradients, shadows, glows, caps labels, numbering, entrance animations) | `app/globals.css:11,24`; grep `gradient\|shadow\|transition\|motion-` in `app/`, `components/` → only the reduced-motion rule | **Low** | Observed |
| UX-12 | Audio presentation | Audio has no visual form: playback is the native `<audio controls>`, the recording indicator is a static dot, there is no level meter | `components/audio-player.tsx:23-30`; `components/recorder.tsx:65-70,101`; level meter listed as not done in `FRONTEND_IMPLEMENTATION_PLAN.md` Phase 6 row | **Medium**: the product's subject is invisible; native controls look different per browser | Observed |
| UX-13 | Copy | One action has three labels ("Sign up", "Get started", "Create account"); generic busy labels ("Working…", "Loading…"); consent sentence leaks internal state ("version 1; the full terms page is not published yet") | `components/user-menu.tsx:33`; `app/page.tsx:14`; `components/signup-form.tsx:106`; `components/upload-voice-form.tsx:272`; `components/voice-profile-select.tsx:31`; `components/upload-voice-form.tsx:206-230` | **Medium** | Observed |
| UX-14 | Auth forms | Google button looks like a secondary button, sits above the fields with no "or" divider; password rules (8-128) appear only as an error after submit; no show/hide | `components/google-button.tsx:9`; `components/signup-form.tsx:68-69,82-87`; `components/login-form.tsx:65-72` | **Low** | Observed |
| UX-15 | Destructive actions | Confirm-delete uses the primary colour; the dialog is an inline block in the page flow, not an overlay; account deletion repeats the pattern | `components/voice-profile-list.tsx:36-42,54`; `components/account-section.tsx:204` (primary-styled button) | **Medium**: delete is not visually distinguished; on a long list the dialog can open off-screen (Inferred) | Observed / Inferred |
| UX-16 | Session expiry | An expired session redirects to `/login?next=…` with no message explaining why; only the generate draft survives, and only in memory | `components/auth-gate.tsx:15-18`; `lib/draft.ts:1-4,10` (the upload form keeps no draft) | **Medium**: an interrupted user does not know what happened | Observed (code) |
| UX-17 | Accessibility | "Upload a file / Record now" is a `role="radio"` group with no arrow-key handling or roving tabindex | `components/upload-voice-form.tsx:161-177` (no `onKeyDown` in the file) | **Medium**: breaks the ARIA radio pattern keyboard users expect | Observed |
| UX-18 | File picker | The upload control shows the unstyled native "Choose File / No file chosen" inside a dashed box | `components/audio-uploader.tsx:48-58`; `shot:profile-m-light` | **Low** | Observed |
| UX-19 | Navigation | No current-page indication in the nav; `aria-current` appears nowhere | `components/user-menu.tsx:39-44`; grep `aria-current` → 0 | **Medium** (WCAG 2.4.8 orientation) | Observed |
| UX-20 | Desktop layout | Forms and lists are fixed to `max-w-xl` inside a `max-w-5xl` container, leaving the right 40% empty; result and history cannot sit beside the form | `components/text-to-speech-form.tsx:144`; `app/(app)/profile/page.tsx:13,19,25,31`; `shot:dashboard-d-dark` | **Low** | Observed |
| UX-21 | History | Past audio sits behind a "Play" click per row; history is the third of four sections on one scroll | `components/history-list.tsx:65-72`; `app/(app)/profile/page.tsx:25-30` | **Low** | Observed |
| UX-22 | Offline | No online/offline detection; network loss is only recognised after a request fails | grep `onLine\|offline` in `app/ components/ hooks/ lib/` → 0 results | **Medium** | Observed (grep) |
| UX-23 | Error fallback | Generic "Something went wrong" with only "Try again"; no route out (home/dashboard); the global fallback renders without the app shell | `components/error-fallback.tsx:6-16`; `app/global-error.tsx:15-21` | **Low** | Observed |
| UX-24 | Theming | Dark mode follows the OS only, no user control | `tailwind.config.ts:4` (`darkMode: "media"`); `app/globals.css:17` | **Low** | Observed |
| UX-25 | Mobile chrome | The header takes two rows at 375 px and a sticky banner is pinned over the bottom of the viewport for unverified users | `components/app-shell.tsx:22`; `components/verification-banner.tsx:11`; `shot:profile-m-light` header | **Low**: intentional (CLS fix, `app-shell.tsx:36-38`) but takes vertical space on a short phone screen (Inferred; not measured) | Observed / Inferred |

### What is already good (keep it)
- Skip link, landmarks, labelled fields, announced errors, 44 px touch targets (`components/app-shell.tsx:12-17`, `components/form-fields.tsx:14-35`).
- Honest, specific error copy for long jobs: "We lost contact before the audio arrived. It may still have been generated: check History" (`components/text-to-speech-form.tsx:40`).
- Every list has loading, empty, error and retry states (`components/voice-profile-list.tsx:28-57`, `components/history-list.tsx:115-146`).
- Reduced-motion is respected globally (`app/globals.css:35-40`).
- Consent is explicit and versioned (`components/upload-voice-form.tsx:196-238`).

---

## 4. Design system proposal

Everything in this section is a **Proposal:** it is not in the repo.

### 4.1 Direction: "the take"
The product's subject is a recorded voice: a *take* (a short clip), its *timecode*, and the question of *trust* (whose voice, with what consent). The look borrows from a quiet studio, not from a SaaS dashboard: warm paper-like neutrals, near-black ink, **one** signal colour, monospaced timecodes, and a single bold element, the waveform of a take. Boldness is spent only there (UX-12); every other surface stays flat and calm.

### 4.2 Palette (light and dark, 6 named roles)
Contrast ratios computed with WCAG 2.x relative luminance from these exact hex values.

| Role | Light | Dark | Used for |
|---|---|---|---|
| `paper` (background) | `#F6F4EF` | `#121413` | page background |
| `surface` | `#FFFFFF` | `#1A1D1C` | inputs, take card, dialogs |
| `ink` (text) | `#17191C` | `#EDEFEC` | body and headings |
| `ink-muted` | `#555B61` | `#A3AAA6` | secondary text, hints |
| `line` (control border) | `#7A7F84` | `#6F7773` | input and button outlines (3:1 rule); hairline dividers use `line` at 40% opacity (decorative, no contrast requirement) |
| `signal` (accent) | `#0B6E69` | `#5CC9BF` | primary button, links, focus ring, waveform |
| `danger` | `#B42318` | `#FF8A80` | errors, destructive confirm |
| `success` | `#1F7A4D` | `#6FD39B` | saved/created confirmations |

Key pairings: `ink` on `paper` **16.0:1** (light) / **16.0:1** (dark); `ink-muted` on `paper` **6.25:1** / **7.8:1**; white on `signal` **6.09:1**; dark `paper` on dark `signal` **9.4:1**; `line` on `paper` **3.68:1** / **4.02:1** (fixes UX-03, from 1.33 / 1.53); `danger` on `paper` **5.98:1** / **8.1:1**; `success` on `paper` **4.84:1** / **10.1:1**; white on `danger` button **6.57:1**; dark `paper` on dark `danger` button **8.1:1**.
Warning (the existing banner) keeps its current amber pair, which already measures 8.95:1 / 10.12:1 (`app/globals.css:13-14,26-27`); it is retained as a sixth role, `notice`.
Accent rule: `signal` marks the single primary action per screen, links, the focus ring and audio. It never fills large areas.

**As shipped in FE-UX0 (`frontend/app/globals.css`):** the table above is implemented with these additions: a `muted` fill (`#ECE8DF` / `#1F2322`), a hairline `border` (`#DDD8CD` / `#2B302E`, dividers and cards only), and `line` (the 3:1 control outline) used on every input, select, textarea and secondary button. Existing token names (`primary`, `foreground`, …) were kept so no component needed renaming; `primary` *is* `signal`. `tests/theme.test.ts` recomputes contrast from the shipped HSL values (text and accent pairs ≥ 4.5:1, control outlines ≥ 3:1, both themes).

### 4.3 Type
| | Choice | Why |
|---|---|---|
| UI and body | **IBM Plex Sans** 400/500/600 | neutral, open, legible at 14-16 px; open licence |
| Time and data | **IBM Plex Mono** 400/500, `tabular-nums` | audio is time: `00:12 / 02:00`, durations and sizes align and do not jitter |
| Loading | `next/font/local` (self-hosted, subset Latin), `display: swap`, size-adjusted fallback | no third-party request (works with the strict CSP, `connect-src 'self'`), no layout shift |

Scale (px / line-height): 12/16 (hint), 14/20 (secondary, buttons), 16/24 (body), 20/28 (section), 28/36 (page title), 44/48 (landing hero, desktop; 32/38 mobile). Weights: 400 body, 500 labels and buttons, 600 headings. Measure: `max-w-prose` (65ch) for reading text; form columns 30-34rem.

### 4.4 Spacing, radius, elevation
- **Spacing:** 4-px base; use 4, 8, 12, 16, 24, 32, 48. Page gutter 16 px (mobile) / 24 px (≥768 px). Vertical rhythm between sections 32 px.
- **Radius:** `control` 6 px (inputs, buttons), `card` 10 px (the take card and dialogs), `pill` 999 px (status badges only). Two values plus the pill; no ad-hoc radii.
- **Elevation:** none by default. Separation comes from `line` hairlines and the `surface`/`paper` step. One exception: dialogs get a scrim (`ink` at 50%) and a 1 px `line` border, no soft glow.

### 4.5 Motion tokens
| Token | Value | Use |
|---|---|---|
| `fast` | 120 ms, ease-out | hover/press feedback, checkbox, toggle |
| `base` | 200 ms, ease-out | dialog and toast appearance, disclosure |
| `wave` | continuous, driven by the audio level or playhead, not by a timer | recording meter, playback cursor |
All durations collapse under `prefers-reduced-motion` (the existing rule, `app/globals.css:35-40`, stays); the waveform then renders static.

### 4.6 Implementation of tokens
Keep the current mechanism (CSS variables → Tailwind colours, `app/globals.css:5-29`, `tailwind.config.ts:8-18`): extend it with `signal`, `danger`, `success`, `line`, `surface`, `ink-muted`, replace `text-red-600 dark:text-red-400` with `text-danger`, and add `fontFamily`, `fontSize`, `borderRadius` entries. **No new styling library.** Add a `data-theme` override so a user toggle can sit beside the OS default (UX-24): `:root[data-theme="dark"]` mirrors the media query.

### 4.7 Component inventory and required states
Primitives (new, in `components/ui/`) first; every one must define the states in the right-hand column. "All" = default, hover, active, `focus-visible`, disabled, loading, error, success where meaningful.

| Component | Replaces | Variants | States required |
|---|---|---|---|
| `Button` | the 8 inline recipes (UX-10) | primary, secondary, quiet, danger; sizes md (44 px), sm | default, hover, active, focus-visible (2 px `signal` ring, 2 px offset), disabled (lower contrast **plus** a stated reason via `aria-describedby` when the cause is not obvious), loading (label stays, spinner replaces icon, `aria-busy`) |
| `Field` (input, textarea, select, checkbox) | `TextField` (`components/form-fields.tsx`) + raw `<select>`/`<textarea>` | text, password (show/hide), textarea with counter, select | default, hover, focus, filled, disabled, error (icon + text, `aria-invalid`), hint always visible |
| `Alert` | scattered `<p role="alert">` and banners | danger, success, notice, info | role chosen by urgency (`alert` vs `status`), dismissible only where safe, icon + text (never colour alone) |
| `Badge` | `StatusChip` (`components/voice-profile-list.tsx:13-22`) | ready, failed, processing | text always present |
| `Dialog` | the two inline pseudo-dialogs (UX-15) | confirm, destructive confirm | focus trap (reuse `hooks/use-dialog.ts`), scrim, Esc, return focus, danger button only in destructive variant |
| `Card` / `Section` | repeated `rounded border p-3` | plain, take | one definition so spacing and radius stay consistent |
| `Take` (**the bold element**) | `AudioPlayer`, recorder preview, history row playback | recording, review, playback | idle, requesting-permission, recording (live level), stopped, loading, playing, paused, ended, error ("can't play, download instead"), expired |
| `Waveform` | none | static or live | decorative to AT (`aria-hidden`); the accessible value is the timecode and the native control semantics |
| `NavLink` | bare `Link`s in `components/user-menu.tsx:39-44` | default, current (`aria-current="page"` + visible marker) | hover, focus-visible, current |
| `StepList` | none | first-run checklist | pending, current, done; **only** for the genuine sequence "Verify email → Create a voice → Generate" (a true sequence, so numbering is legitimate) |

### 4.8 Principles (what makes this UI recognisably this product)
1. **Show the voice, not decoration.** The only graphic is the waveform of a real take; no illustrations, no gradients.
2. **Time is monospaced.** Every duration, timecode and size uses the mono face.
3. **Consent is part of the interface, not a footnote.** Whose voice, what terms and what is stored are stated at the point of action, in plain words.
4. **One primary action per screen**, in `signal`; everything else is quiet.
5. **Say what happened and what to do next**, in sentence case; no apology, no jargon, no internal state (UX-13).
6. **Never block silently.** A control that cannot be used says why, next to itself.

### 4.9 Review against the generic-AI-look list (Step 3D)
| Tell | Risk in this direction | Guard written into the plan |
|---|---|---|
| Identical rounded cards with soft shadow | High: a `Card` primitive invites wrapping every block | Cards only for the *take* and dialogs; lists use hairline rows; **no shadows** (§4.4) |
| Gradient washes / glows / purple-pink / dark + neon | Low for gradients; medium for "dark background + one bright accent": the dark-mode `signal` (`#5CC9BF`) on near-black is close to that look | Dark `signal` is deliberately desaturated and used only for small elements; large areas stay `ink`/`surface` |
| Tracked-out ALL-CAPS labels | Low | banned: sentence case everywhere (§4.8 rule 5) |
| Numbered 01/02/03 markers on non-sequences | Medium: a landing "how it works" section tempts numbered cards | Numbering is used **only** for the real first-run sequence (`StepList`); landing "how it works" uses plain sentences |
| One accented word in a headline | Low | banned |
| Fade-and-slide on every section, hover transitions on every card | Low | motion limited to §4.5 triggers |
| Emoji / stock icons as hierarchy | Low | icons only inside `Alert` and `Button` where they carry meaning; no emoji |
| Marketing copy that says nothing specific | High: landing copy defaults to generic claims | Landing copy must use concrete statements (§5.3): sample length, what is stored, how long clips are kept (30 days, `components/history-list.tsx:49`) |
| Product-agnostic palette | Medium: teal on warm paper is common in wellness and finance products | Kept deliberately, because contrast and calm suit a trust-heavy product, **but** the accent is tied to audio by also being the waveform colour; if the owner has a brand colour, swap `signal` only (Open question OQ-1) |

**Outcome of the review:** no part of the direction reads as a default once the guards above are applied. The weakest point is the palette, which is tasteful but not unique to audio; I kept it for contrast and calm and flagged it for the owner (OQ-1) rather than inventing a brand.

### 4.10 Motion principles
- **Allowed:** feedback to a user action (press, toggle, disclosure, dialog/toast appearance, 120-200 ms); the **live waveform** while recording and the **playhead** while playing (state, not decoration); one deliberate moment: when a generated take finishes, its waveform draws in once (≤400 ms, skipped under reduced motion).
- **Banned:** entrance animations on page load or scroll, hover lift on cards, looping decorative motion, parallax, auto-playing audio on arrival (history playback after an explicit Play click is fine, `components/history-list.tsx:59`).

---

## 5. Navigation and user-journey redesign

### 5.1 Information architecture (Proposal)
Today: `/` · `/signup` · `/login` · `/dashboard` · `/profile` (voices + history + account). 
Proposed: split by job, keep URLs stable with redirects.

| Route | Job | Nav label | Notes |
|---|---|---|---|
| `/` | decide to sign up | (logo) | trust-building landing (§5.3) |
| `/studio` (was `/dashboard`) | **make speech** | **Studio** | the generator; first-run checklist when no ready voice exists |
| `/voices` (new) | create and manage voices | **Voices** | create form, list, failed rows |
| `/history` (new) | replay past speech | **History** | list with inline players |
| `/account` (was the last section of `/profile`) | name, email status, delete account | **Account** | |
| `/dashboard`, `/profile` | n/a | n/a | 308 redirects to `/studio`, `/voices` (so emailed or bookmarked links survive) |

Assumption: route renames need no backend change (the API is route-independent); e2e and docs referencing `/dashboard` and `/profile` must be updated (§7 U1).

### 5.2 App shell wireframe
```
Desktop (≥768)
┌────────────────────────────────────────────────────────────────────────┐
│ [degraded-service notice: only when /health/ready is not ok]           │
├────────────────────────────────────────────────────────────────────────┤
│ CloneVoice    Studio  Voices  History              Ada ▾  (Account,    │
│               ▔▔▔▔▔▔                                       Sign out)   │
├────────────────────────────────────────────────────────────────────────┤
│  <page title>                                                          │
│  <page content: one primary action>                                    │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│ Generated voices are AI-synthesised. Use only voices you may clone.    │
└────────────────────────────────────────────────────────────────────────┘
Mobile (375): wordmark + "Menu" disclosure OR bottom tab bar [Studio|Voices|History|Account]
```
- Current page marked with an underline **and** `aria-current="page"` (UX-19).
- The verification notice moves from the sticky bottom banner to **one** inline `Alert` at the top of Studio and Voices, the only places it matters (UX-07, UX-25). It is also the first item of the first-run checklist.
- Mobile: a bottom tab bar replaces the two-row header (UX-25). Assumption: a four-item tab bar fits 375 px at 44 px targets (4 × 93 px).

### 5.3 First-run journey (target: first result in under 3 minutes, no dead ends)
```
Landing ─► Sign up ─► Studio (first-run) ─► Voices: create ─► Studio ─► Result
                           │                       ▲
   checklist:  ① Verify email   ② Create a voice   ③ Generate speech
```
1. **Landing** (UX-04). Concrete content, no marketing filler: what it does in one sentence; **three plain statements** ("You need a 10-30 second recording of a voice you have the right to use", "Clips are kept 30 days, then deleted", "Every result is labelled AI-generated"); a *real* example take only if a consented sample exists (Assumption: none exists today, so omit rather than fake); primary "Create account", secondary "Sign in".
2. **Sign up.** Show the password rule before typing ("8 to 128 characters") (UX-14); one label for the action everywhere: "Create account" (UX-13); Google button gets a divider ("or use email") and the provider mark.
3. **Studio, first run.** If the user has no ready voice, replace the empty picker with a `StepList` (UX-06): ① Verify your email (done/pending, with Resend) ② Create a voice ③ Generate speech. The generator is shown but disabled with a stated reason ("Create a voice first"), and the primary action is the current step's button.
4. **Create a voice** (`/voices`). Name → sample (upload **or** record) → consent → "Save voice". On success the form is replaced by a success `Alert` with a primary button **"Generate speech with “<name>”"** that goes to Studio with the voice preselected (UX-06).
5. **Generate.** Text area with a live counter, a character hint, and the voice preselected. While generating: a determinate-looking but honest state: the `Take` card in "loading" shows elapsed time in mono and a calm indeterminate bar; Cancel stays available. On finish: the take card with waveform, play, download, and actions "Edit text" and "Generate again" (UX-08).

### 5.4 Primary-screen wireframe: Studio (desktop)
```
┌ Studio ───────────────────────────────────────────────────────────────┐
│ [Alert notice] Verify ada@example.com to generate speech. [Resend]     │
│                                                                        │
│ Voice  [ My voice            ▾ ]            ┌ Your take ─────────────┐ │
│                                              │ ▁▂▅▇▅▃▂▁▂▄▆▇▅▂▁       │ │
│ Text                                         │ ▶  00:03 / 00:07      │ │
│ ┌──────────────────────────────┐             │ [Download WAV]        │ │
│ │                              │             │ “Hello there…”        │ │
│ └──────────────────────────────┘             │ [Edit text][Again]    │ │
│ 0 / 500 · Plain text works best               └───────────────────────┘ │
│ [ Generate speech ]  (disabled: "Verify your email first")             │
└───────────────────────────────────────────────────────────────────────┘
Mobile: single column; the take card appears below the form and scrolls into view when ready.
```
This also answers UX-20: on desktop the form and result sit side by side.

### 5.5 Voices screen wireframe (mobile)
```
Voices
[Alert: success / failure for the last action]
┌ Add a voice ─────────────────┐
│ Name  [__________]           │
│ ( Upload a file | Record )   │  ← arrow-key radio group (UX-17)
│ ┌ Take ──────────────────┐   │
│ │ ▁▂▃▅▃▂▁   00:00 / 02:00│   │
│ │ [● Record]             │   │
│ └────────────────────────┘   │
│ ☐ I have the right to use this voice and accept the terms (read)     │
│ [ Save voice ]                                                       │
└──────────────────────────────┘
Your voices
 My voice  [Ready]                         [Use in Studio] [Delete]
 Broken sample [Failed] Couldn't be processed. [Delete]
```

---

## 6. Resilience standards

Rules every new or changed screen must satisfy. They **extend** (not replace) the engineering plan's R1-R18 (`FRONTEND_IMPLEMENTATION_PLAN.md` §6); the existing behaviour is preserved and only gains UI.

| ID | Rule | Existing behaviour retained |
|---|---|---|
| **UR1 Loading** | Skeleton shaped like the final content (same height, so no layout shift); `aria-busy`; a spinner only on a button | `components/voice-profile-list.tsx:28-35`, `history-list.tsx:115-122` |
| **UR2 Empty** | Every empty state states the reason **and** shows the single next action as a `Button` (not a text link) | text-only today: `voice-profile-list.tsx:51-57`, `history-list.tsx:140-146` |
| **UR3 Error** | `Alert` with: what happened, what the user can do, a retry when safe. No raw server text for 5xx; no apology | `lib/errors.ts` kinds; `text-to-speech-form.tsx:24-44` |
| **UR4 Disabled needs a reason** | A disabled primary action renders its cause next to it and links it by `aria-describedby` (fixes UX-07, UX-09) | gap today |
| **UR5 Offline** | Listen to `online`/`offline` events; when offline show a non-blocking `Alert`, disable network actions with reason; auto-clear on `online` and refetch active queries (UX-22) | health poll covers server-down only (`components/degraded-banner.tsx`) |
| **UR6 Retry/backoff** | Idempotent GETs: automatic retry as in R5; user-initiated retry button elsewhere. Never auto-retry POSTs (synthesize, upload, signup, refresh, delete account) | R5 |
| **UR7 Double submit** | Control disabled at once and a ref guard; the label shows progress | `signup-form.tsx:33-35`, `text-to-speech-form.tsx:86-98` |
| **UR8 Cancellation** | Any request > 5 s offers Cancel; copy says the server may still finish and points to History | `text-to-speech-form.tsx:107-113,217-225` |
| **UR9 Auth expiry** | Redirect to sign-in **with an explanatory message** ("Your session ended. Sign in to continue") and return to the same page; the generate draft survives; the upload form must keep the name and consent but **never re-upload a file silently** (UX-16) | in-memory draft only: `lib/draft.ts:1-10` |
| **UR10 Status codes** | 401 → UR9; 403 → by kind (unverified → verification `Alert`; wrong password → field error); 404 → refresh the list and say the item is gone; 409 → by kind; 413/422 → inline field error; 429 → countdown, control disabled; 5xx → generic message + retry; status 0 → UR5 wording | `lib/errors.ts`, R3 |
| **UR11 Upload/job failures** | Pre-validate type and size; progress for upload; after an ambiguous failure (network/timeout) re-fetch the list before telling the user to retry; a failed profile row is shown with Delete | `upload-voice-form.tsx:28-44,130-131` |
| **UR12 Microphone** | Distinct copy for denied, no device, busy, insecure context and unsupported browser; always offer file upload as the fallback; release the stream on every exit | `lib/recording.ts`, `components/recorder.tsx:114-125` |
| **UR13 Playback failure** | The `Take` shows "can't play" and keeps Download available; expired audio says so and offers "Generate again" with the same text | `audio-player.tsx:17-21`, `history-list.tsx:46-52` |
| **UR14 Stale data / tabs** | Refetch on focus; mutations invalidate; a tab that signs out redirects the others (existing broadcast) | R11 |
| **UR15 Error boundaries** | Boundary at root, per route group, and around `Take`; the fallback offers **"Try again" and "Go to Studio"**; the global fallback includes the wordmark and footer so the page never looks blank (UX-23) | `components/error-fallback.tsx:6-16`, `app/global-error.tsx:15-21` |
| **UR16 Unsupported browsers** | Feature-detect (`MediaRecorder`, WEBM) after mount and degrade to upload; never show a broken control | `upload-voice-form.tsx:65-69` |
| **UR17 No layout shift** | Reserve space for async content; banners render in a reserved slot or inline in the page, not above everything | `app-shell.tsx:36-38` rationale |

---

## 7. Phase-wise plan

Order: tokens and foundation → shell and navigation → core flows → states and resilience → the voice-take component → motion and polish → accessibility and performance → release hardening. Each phase leaves the app shippable. Existing unit (Vitest), e2e (Playwright), axe, Lighthouse and smoke suites stay green at every phase; tests that assert old copy or routes are updated in the same phase as the change (`tests/*.test.tsx`, `e2e/*.spec.ts` assert labels such as "Generate speech" and routes such as `/dashboard`: **Assumption:** based on the earlier plan, files not re-read this session).

New test types introduced: **visual regression** (Playwright `toHaveScreenshot`, 3 widths × light/dark, on the public routes and, with the existing API mocks, the signed-in routes; threshold 0.2%), and a **token lint** (a unit test that fails on hardcoded `red-`, `indigo-`, `#hex` or `rgb(` in `components/` and `app/`).

### U0 — Tokens, type and primitives
- **Goal:** one source of truth for colour, type, spacing, radius and states, and the primitives that use it. No visible layout change yet beyond the new palette, font and focus rings.
- **Tasks**
  - U0.1 Extend `app/globals.css` and `tailwind.config.ts` with the §4.2-4.6 tokens (`signal`, `danger`, `success`, `line`, `surface`, `ink-muted`, `notice`), light/dark, plus a `data-theme` override and a small theme toggle slot (UX-01, UX-24).
  - U0.2 Self-host IBM Plex Sans and Mono with `next/font/local`; add `fontFamily`, `fontSize`, `borderRadius`; apply to `<body>` (UX-02).
  - U0.3 Move control borders to `line` (≥3:1) in a shared Field/Button style (UX-03).
  - U0.4 **(Button, Alert, Badge done in FE-UX1; Input, Select, Textarea in FE-UX2; Card deferred to U3/U4, where cards are allowed)** Build `components/ui/{button,field,alert,badge,card}.tsx` with the §4.7 states, including a `focus-visible` ring and a stated-reason disabled pattern (UX-09, UX-10).
  - U0.5 **(done for buttons, field-level and form-level errors, and StatusChip → Badge in FE-UX1; input/select/textarea migrated in FE-UX2)** Replace every inline recipe and every `text-red-600 dark:text-red-400` with the primitives and `text-danger`; delete `StatusChip` in favour of `Badge` (UX-01, UX-10).
  - U0.6 **(done, FE-UX0; closed in FE-UX21)** Replace the accent `243 75% 50%` with `signal`; document the swap point for a brand colour (UX-11).
- **Files likely affected:** `app/globals.css`, `tailwind.config.ts`, `app/layout.tsx`, `components/form-fields.tsx`, `components/ui/*` (new), and every component that carries a button/error class (`login-form`, `signup-form`, `upload-voice-form`, `text-to-speech-form`, `voice-profile-list`, `history-list`, `recorder`, `account-section`, `audio-uploader`, `app-shell`, `user-menu`, banners).
- **Edge cases:** dark mode parity; `forced-colors` (Windows high contrast): focus ring and borders must not rely on colour alone; reduced motion; no flash of unstyled text (size-adjusted fallback font); CSP: fonts self-hosted, no new origins.
- **Tests:** *Unit:* token lint; Button/Field/Alert state matrix (RTL: disabled reason announced, loading `aria-busy`, error `aria-invalid`). *Visual regression:* baseline of every public route. *Accessibility:* axe on the primitives page (a dev-only route or Vitest render) and on existing pages; computed-contrast assertion for each token pair listed in §4.2. *e2e:* existing suite unchanged and green.
- **Exit criteria:** zero hardcoded colours outside the token files (lint passes); every token pair meets §4.2 ratios (asserted); focus ring visible on every interactive element in a keyboard walk-through; font loads with no third-party request (CSP report-only silent) and CLS ≤ 0.02 (`npm run perf`).
- **Dependencies:** none. **Risks:** large mechanical diff touching ~15 files (mitigate: land primitives first, migrate component by component with the visual-regression baseline); font subset missing glyphs (Assumption: Latin-only copy).

### U1 — App shell, navigation and information architecture
- **Goal:** a user always knows where they are and what the main action is; the three jobs (make speech, manage voices, replay history) have their own homes.
- **Tasks**
  - U1.1 **(done, FE-UX3)** Introduce `NavLink` with `aria-current="page"` and a visible marker (UX-19).
  - U1.2 **(done, FE-UX3; the generator is `/generate`, per §11.2)** Split `app/(app)/profile/page.tsx` into `/voices`, `/history`, `/account`; rename `/dashboard` → `/studio`; add 308 redirects from `/dashboard` and `/profile`; update titles, headings and the nav labels (Studio · Voices · History · Account) (UX-05, UX-21).
  - U1.3 **(done, FE-UX4)** Mobile bottom tab bar in place of the two-row header; desktop keeps the top bar (UX-25).
  - U1.4 **(done, FE-UX4)** Replace the sticky bottom verification banner with one inline `Alert` on Studio and Voices; keep the reserved space so there is no layout shift (UX-07, UX-25).
  - U1.5 **(done, FE-UX4)** Desktop two-column layout for Studio (form | take) and Voices (create | list) (UX-20).
  - U1.6 **(done, FE-UX3; no smoke/RUNBOOK references existed)** Update `AuthGate` redirect targets, `next=` sanitiser allow-list, smoke script and RUNBOOK paths for the renamed routes.
- **Files likely affected:** `components/app-shell.tsx`, `components/user-menu.tsx`, `components/verification-banner.tsx`, `app/(app)/*`, `app/(public)/*` (redirect targets), `components/auth-gate.tsx`, `lib/auth/next-path.ts`, `middleware.ts` (redirects), `smoke/*`, `frontend/RUNBOOK.md`, e2e specs.
- **Edge cases:** deep links and emailed links to `/dashboard`, `/profile` still work (redirect, query and fragment preserved); `next=` to an old path is mapped; browser back; a signed-out user opening `/voices` goes to login and returns there; narrow (320 px) tab bar; the keyboard order of the new nav; screen-reader landmark labels are unique.
- **Tests:** *Unit:* `sanitizeNext` accepts new paths and maps old ones; `NavLink` sets `aria-current`. *Integration (MSW):* each new route renders its own content and the old paths redirect. *e2e:* signup → first-run → each nav item; old URLs redirect; tab bar at 375 px. *Visual:* shell at 3 widths. *Accessibility:* axe on every route; heading order (one `h1` per page).
- **Exit criteria:** every page has exactly one `h1` matching its nav label; current page is exposed to AT and visible; old URLs return 308 and land correctly; no CLS regression (`npm run perf`, layout-shift e2e).
- **Dependencies:** U0. **Risks:** route rename breaks bookmarks/e2e/docs (mitigate with redirects and a grep checklist); tab bar vs. sticky banners overlapping on small screens.

### U2 — Core flows: landing, first run, generate
- **Goal:** a new user reaches a first generated take with no dead end and no unexplained blocked button.
- **Tasks**
  - U2.1 **(done, FE-UX6)** Landing page: specific content per §5.3 (one-sentence value, three plain statements on sample length, retention and labelling, consent promise); "Create account" primary, "Sign in" secondary; no invented demo audio (UX-04).
  - U2.2 **(done, FE-UX6; Google mark FE-UX22)** Auth forms: password rule shown before typing; show/hide control; Google button restyled with divider and provider mark; one action label "Create account" everywhere (UX-13, UX-14).
  - U2.3 **(done, FE-UX5)** Studio first-run `StepList` (verify email → create a voice → generate), with the generator disabled **and the reason shown** until a ready voice and a verified email exist (UX-06, UX-07).
  - U2.4 **(done, FE-UX5)** Voices: after a successful create, show a success `Alert` with "Generate speech with “<name>”" that opens Studio with the voice preselected; use `Link`, not `<a href>` for in-app navigation (UX-06).
  - U2.5 **(done, FE-UX7)** Generate: honest progress state (elapsed time in mono, indeterminate bar, Cancel), result `Take` with Download, "Edit text" and "Generate again" (UX-08).
  - U2.6 **(done, FE-UX6)** Copy pass: replace "Working…", "Loading…" and the consent sentence that exposes "version 1; the full terms page is not published yet"; show the terms version only when a URL exists, otherwise a plain "Terms are being finalised" line (UX-13). Sentence case; buttons name the action ("Save voice", "Generate speech").
  - U2.7 **(done, FE-UX7)** Replace the native file input chrome with a styled drop zone and visible button (keeping the real `<input type="file">` for AT and the existing validation) (UX-18).
- **Files likely affected:** `app/page.tsx`, `components/signup-form.tsx`, `login-form.tsx`, `google-button.tsx`, `text-to-speech-form.tsx`, `voice-profile-select.tsx`, `upload-voice-form.tsx`, `audio-uploader.tsx`, new `components/step-list.tsx`.
- **Edge cases:** verified-but-no-voice, voice-but-unverified, both missing, voice failed only (shows Failed row + create prompt); preselected voice that was deleted (404 → list refresh → message); long text near 500 chars; double submit; Cancel mid-generate; user leaves page (existing `beforeunload`); screen reader hears step state changes (`aria-live="polite"` region).
- **Tests:** *Unit:* StepList state derivation (3 inputs → 8 combinations); copy constants; consent text with/without terms URL. *Integration (MSW):* all four first-run combinations; create-voice success shows the CTA; Generate disabled reasons. *e2e (real backend):* signup → verify via console log → create voice → CTA → generate → play (extends the existing synthesis spec). *Visual:* landing, signup, Studio first-run, Voices. *Accessibility:* axe; the disabled reason is exposed through `aria-describedby`.
- **Exit criteria:** from a fresh account to a played take takes ≤ 6 interactions after email verification (counted in the e2e); no button is disabled without visible text saying why; no copy string matches the banned list ("Submit", "Working…", "Loading…" as a label, "Sign up" as the action name).
- **Dependencies:** U0, U1. **Risks:** copy changes break many tests (update with the change); the landing statements must match backend facts (30-day retention is from `components/history-list.tsx:49` and `OUTPUT_RETENTION_DAYS`: confirm before publishing, OQ-3).

### U3 — States and resilience
- **Goal:** implement §6 so no failure is silent, ambiguous or blank.
- **Tasks**
  - U3.1 **(done, FE-UX8)** `Dialog` primitive (overlay, scrim, focus trap via `hooks/use-dialog.ts`, return focus) with a destructive variant using `danger`; migrate delete-voice and delete-account (UX-15).
  - U3.2 **(done: message FE-UX8, draft restore FE-UX24)** Session-expiry message and return path: `/login?reason=expired&next=…` shows "Your session ended. Sign in to continue." and restores the page; persist non-sensitive form state (voice name, consent) in memory across the redirect; never the file or the text beyond what `lib/draft.ts` already holds (UX-16).
  - U3.3 **(done, FE-UX9)** Offline handling: `useOnline` hook; global `Alert`; network actions disabled with reason; refetch on reconnect (UX-22).
  - U3.4 **(done, FE-UX9)** Error fallback with "Try again" and "Go to Studio"; global-error includes wordmark and footer; boundary around the take (UX-23).
  - U3.5 **(done, FE-UX9)** Empty states become `Button` CTAs (UR2); skeletons match final layout (UR1).
  - U3.6 **(done, FE-UX4/5; closed in FE-UX21: `components/verify-email-alert.tsx` on Voices, the first-run checklist step on Generate, so each page shows the notice once; the sentence is duplicated in the two files)** Verification gate component: one `VerifyEmailAlert` reused by Studio and Voices, replacing three separate notices (UX-07).
- **Files likely affected:** `components/ui/dialog.tsx` (new), `voice-profile-list.tsx`, `account-section.tsx`, `auth-gate.tsx`, `login-form.tsx`, `hooks/use-online.ts` (new), `error-fallback.tsx`, `app/global-error.tsx`, `lib/draft.ts`.
- **Edge cases:** dialog open when the session expires; delete while offline; 404 on delete (already gone) shows "already deleted"; Esc and scrim click both cancel except while a request is in flight; browser back closes the dialog; offline → online during an in-flight request; multiple tabs.
- **Tests:** *Unit:* `useOnline`; draft persistence rules (text never persisted beyond memory, R16). *Integration (MSW):* each status code in UR10 produces its message; offline toggled with `navigator.onLine` stub; 401 mid-generate returns with the draft. *e2e:* Playwright `context.setOffline(true)` during upload and generate; kill-backend test (exists in the resilience spec: extend); expired access token mid-action. *Accessibility:* dialog focus trap, Esc, return focus (extends `e2e/dialog-keyboard.spec.ts`). *Visual:* dialog, error states.
- **Exit criteria:** every status code in UR10 has a tested, user-readable outcome per screen; offline and online transitions announce themselves; no screen can render blank after a thrown error (error-boundary test per route group).
- **Dependencies:** U0-U2. **Risks:** focus trap regressions (existing tests cover; extend); restoring state after login must not leak data between accounts (clear on logout, assert).

### U4 — The voice take (the one bold element)
- **Goal:** make audio visible and consistent: one `Take` component for recording, review and playback.
- **Tasks**
  - U4.1 **(done, FE-UX10)** `Waveform` renderer: peaks computed with `AudioContext.decodeAudioData` on the existing blob (client-side, lazy-loaded); static SVG/canvas; `aria-hidden` (UX-12).
  - U4.2 **(done, FE-UX11)** Live level meter during recording via `AnalyserNode` (lazy-loaded with the recorder), a pulsing dot driven by level, not by a timer (UX-12).
  - U4.3 **(done, FE-UX10)** `Take` wrapping a native `<audio>` element (keeps AT, keyboard and codec behaviour) with a custom visual layer: play/pause, seek, mono timecode, Download; falls back to native controls when peaks cannot be computed (UX-12).
  - U4.4 **(done, FE-UX10)** Use `Take` in the recorder preview, the Studio result and each history row (history rows lazy-load audio only on Play, as today).
- **Files likely affected:** `components/audio-player.tsx` (replaced), `components/recorder.tsx`, `hooks/use-recorder.ts`, `history-list.tsx`, new `components/take.tsx`, `components/waveform.tsx`, `lib/audio-peaks.ts`.
- **Edge cases:** decode fails (codec, corrupt) → fallback to native controls plus Download; very long clips (≤ 120 s) decode off the main thread or downsample; Safari/WebKit decoding differences; `AudioContext` blocked until a gesture; microphone revoked mid-recording; tab hidden while recording; blob URL lifecycle (existing `useObjectUrl`); 50-generation soak must still show no leak (existing soak spec).
- **Tests:** *Unit:* peak extraction on a synthetic WAV (known peaks); timecode formatter; fallback path. *Integration:* `Take` states (idle → playing → ended; error). *e2e:* record with Chromium fake-media flags, see the meter move, preview, upload (extends the recording spec); soak spec unchanged and green. *Visual:* take states (static only; animation disabled in tests). *Accessibility:* the accessible name and play state; timecode announced politely and rate-limited.
- **Exit criteria:** every place that plays or records audio uses `Take`; waveform decode failure never blocks playback or download; the recorder's JS cost stays lazy (public-route JS budget in `perf/budget.mts` unchanged); soak shows no leaked object URLs.
- **Dependencies:** U0, U2 (placement). **Risks:** custom player accessibility regressions (mitigated by wrapping the native element); decode cost on low-end phones (downsample, cap 120 s).

### U5 — Motion and polish
- **Goal:** apply the §4.10 principles and nothing else.
- **Tasks**
  - U5.1 **(done, FE-UX12)** Implement `fast`/`base` tokens on button press, checkbox, disclosure, dialog and toast.
  - U5.2 **(done, FE-UX12)** The single deliberate moment: waveform draws in once when a generated take completes (≤ 400 ms).
  - U5.3 **(done, FE-UX12)** Verify the reduced-motion path: all durations collapse and the waveform is static; extend the global rule beyond `animation-duration`/`transition-duration` to cover canvas/RAF-driven animation.
  - U5.4 **(done, FE-UX12)** Empty-state and error-state illustration pass: none; typography only (explicit non-goal).
- **Files likely affected:** `app/globals.css`, `components/ui/*`, `components/take.tsx`.
- **Edge cases:** reduced motion on; background tab (RAF throttling); low-power devices; no layout shift from animations (transform/opacity only).
- **Tests:** *Unit:* the RAF-driven animation checks `matchMedia("(prefers-reduced-motion: reduce)")`. *e2e:* with `reducedMotion: "reduce"` emulation, assert no running animations (`document.getAnimations()` is empty). *Visual:* screenshots with animations disabled. *Performance:* CLS stays ≤ 0.02.
- **Exit criteria:** motion appears only in the listed places; reduced-motion produces no animation; no CLS regression.
- **Dependencies:** U0, U4. **Risks:** scope creep: anything not in §4.10 is rejected.

### U6 — Accessibility and performance
- **Goal:** WCAG 2.2 AA across all flows and the existing performance budgets, with the new fonts and take component.
- **Tasks**
  - U6.1 **(done, FE-UX13)** Arrow-key and roving-tabindex handling for the "Upload a file / Record" radio group (or replace with a native radio group) (UX-17).
  - U6.2 **(done, FE-UX14)** Re-verify contrast (UX-03), focus-visible (UX-09), `aria-current` (UX-19) with automated and manual checks; forced-colors pass.
  - U6.3 Manual NVDA and VoiceOver pass over signup, create voice, generate, history, account (carried over from the engineering plan, still needs a person).
  - U6.4 **(done, FE-UX15; verification only, no code change)** Performance: confirm the font and `Take` code do not break the `perf/budget.mts` budgets (JS ≤ 200 KB gz on public routes, LCP ≤ 2.5 s, CLS ≤ 0.02); lazy-load `Take` waveform code.
  - U6.5 **(done, FE-UX14)** Touch targets ≥ 44 px on the tab bar and icon buttons; zoom 200-400% reflow at 320 px.
- **Files likely affected:** `upload-voice-form.tsx`, `ui/*`, `perf/budget.mts` (only if a budget changes, with justification), `e2e/a11y.spec.ts`, `e2e/responsive.spec.ts`.
- **Edge cases:** `prefers-contrast: more`; Windows high contrast; screen reader announcing both status and timecode; keyboard-only drag-and-drop alternative (the file button).
- **Tests:** *Accessibility:* axe on every route in light and dark, zero serious/critical; keyboard-only e2e of each flow; token contrast assertions. *Performance:* Lighthouse CI (`npm run perf`) on public routes. *Manual:* screen-reader checklist (a person).
- **Exit criteria:** axe clean; all flows completable by keyboard alone; budgets met; manual screen-reader pass signed off.
- **Dependencies:** U0-U5. **Risks:** the manual pass needs a person and tools this host lacks.

### U7 — Release hardening
- **Goal:** cross-browser and regression safety before the redesign ships.
- **Tasks**
  - U7.1 **(done, FE-UX17; Chromium 44/45, Firefox 36/36 with 9 Chromium-only skips; WebKit not run)** Run the full e2e on Chromium and Firefox (Safari/WebKit: `npx playwright install webkit` was enough on this host, no `install-deps`; a mocked structural smoke now runs there, FE-UX27; the full real-backend e2e was not run on WebKit).
  - U7.2 **(done, FE-UX18 public routes, FE-UX19 signed-in routes)** Freeze visual-regression baselines at 375/768/1280 in light and dark; review diffs by eye once.
  - U7.3 **(done, FE-UX16)** Update `frontend/README.md`, `RUNBOOK.md`, smoke script routes and the engineering plan's log.
  - U7.4 **(done, FE-UX20; `frontend/RUNBOOK.md`)** Staged rollout note: ship tokens/primitives (U0) first, then IA (U1), so a regression is easy to bisect.
- **Tests:** full unit + e2e + axe + Lighthouse + smoke; contract tests unchanged (no backend change).
- **Exit criteria:** §9 fully ticked. **Dependencies:** U0-U6. **Risks:** Safari unverified; visual baselines flaky across OS fonts (mitigate: run baselines in the same container/OS as CI).

---

## 8. Traceability matrix

Finding → Phase → Task → Test type. **U**=unit, **I**=integration (MSW), **E**=e2e, **V**=visual regression, **A**=axe/accessibility, **P**=Lighthouse/perf, **M**=manual.

| Finding | Phase | Task(s) | Tests |
|---|---|---|---|
| UX-01 tokens/colours | U0 | U0.1, U0.5 | U (token lint), V |
| UX-02 typography | U0 | U0.2 | V, P |
| UX-03 border contrast | U0, U6 | U0.3, U6.2 | U (contrast), A, V |
| UX-04 landing | U2 | U2.1 | I, V, A, E |
| UX-05 IA | U1 | U1.2 | I, E, A |
| UX-06 first-run dead end | U2 | U2.3, U2.4 | U, I, E |
| UX-07 verification gate | U1, U2, U3 | U1.4, U2.3, U3.6 | I, E, A |
| UX-08 generate feedback | U2 | U2.5 | I, E, V |
| UX-09 interaction states | U0, U6 | U0.4, U6.2 | U, A, V |
| UX-10 components | U0 | U0.4, U0.5 | U, V |
| UX-11 accent | U0 | U0.6 | V |
| UX-12 audio presentation | U4 | U4.1-U4.4 | U, I, E, V, A |
| UX-13 copy | U2 | U2.2, U2.6 | U, I |
| UX-14 auth forms | U2 | U2.2 | I, V, A |
| UX-15 destructive actions | U3 | U3.1 | I, E, A |
| UX-16 session expiry | U3 | U3.2 | I, E |
| UX-17 radio keyboard | U6 | U6.1 | U, E, A |
| UX-18 file picker | U2 | U2.7 | I, V, A |
| UX-19 current page | U1, U6 | U1.1, U6.2 | U, A |
| UX-20 desktop layout | U1 | U1.5 | V, E |
| UX-21 history | U1 | U1.2 | I, E |
| UX-22 offline | U3 | U3.3 | U, I, E |
| UX-23 error fallback | U3 | U3.4 | I, E |
| UX-24 theming | U0 | U0.1 | U, V |
| UX-25 mobile chrome | U1 | U1.3, U1.4 | E, V, P |

**Reverse check (every task maps to a finding):** U0.1→01,24 · U0.2→02 · U0.3→03 · U0.4→09,10 · U0.5→01,10 · U0.6→11 · U1.1→19 · U1.2→05,21 · U1.3→25 · U1.4→07,25 · U1.5→20 · U1.6→05 (supports the rename) · U2.1→04 · U2.2→13,14 · U2.3→06,07 · U2.4→06 · U2.5→08 · U2.6→13 · U2.7→18 · U3.1→15 · U3.2→16 · U3.3→22 · U3.4→23 · U3.5→(UR1/UR2: supports 06,07) · U3.6→07 · U4.1-4.4→12 · U5.1-5.4→12,08 (motion principles; no separate finding) · U6.1→17 · U6.2→03,09,19 · U6.3→(carried-over manual pass; supports 17,19) · U6.4→(budget guard for U0.2, U4) · U6.5→25 · U7→(release gate). Tasks U3.5, U5.x, U6.3, U6.4 and U7 have no single owning finding; they enforce the standards in §6, §4.10 and §9 rather than fix a specific observed defect.

---

## 9. Definition of Done

**Accessibility**
1. axe: zero serious/critical issues on every route, light and dark; token contrast pairs asserted (text ≥ 4.5:1, control boundaries ≥ 3:1).
2. Every flow (signup, login, create voice by file and by recording, generate, history, delete voice, delete account) completes by keyboard alone with a visible focus ring; the current page is exposed with `aria-current`.
3. Manual NVDA and VoiceOver pass recorded by a person (carried over, DoD 11 of the engineering plan).
4. Touch targets ≥ 44 px; reflow at 320 px and 400% zoom; forced-colors usable.

**Responsive and cross-browser**
5. Layouts verified at 320, 375, 768, 1280, 1920 px, light and dark; visual-regression baselines committed.
6. Chromium and Firefox e2e green; Safari/WebKit smoke-tested or explicitly listed as not run.

**States and resilience**
7. Every screen and component has the states in §4.7; no control is disabled without a visible reason (UR4).
8. Every status code in UR10, offline, microphone denial, playback failure and expired audio has a tested user-readable outcome; no thrown error renders a blank page.

**Motion and design**
9. `prefers-reduced-motion` produces no animation; motion exists only where §4.10 allows.
10. No hardcoded colour or one-off radius outside the token files (lint); no gradient, shadow, ALL-CAPS label or numbered non-sequence anywhere.

**Performance**
11. Existing budgets hold (`perf/budget.mts`): LCP ≤ 2.5 s, public-route JS ≤ 200 KB gz, CLS ≤ 0.02; fonts self-hosted; 50-generation soak shows no leak.

**Regression**
12. Unit, integration, e2e, axe, Lighthouse and smoke suites pass with zero failures; contract tests unchanged (no backend change); engineering-plan Task Status Log updated.

### 9.1 Status against this checklist (2026-10-09, FE-UX31)

"Re-run" = executed today against the current `main`; "per log" = recorded in `FRONTEND_IMPLEMENTATION_PLAN.md` earlier and not re-checked now.

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | axe clean, token contrast asserted | **Met** | Re-run: e2e `a11y` passes on Chromium and Firefox (and WebKit over HTTPS, FE-UX29); `tests/theme.test.ts` in the 459 unit tests |
| 2 | Every flow by keyboard alone, `aria-current` | **Met** | FE-UX33 (`bf84a53`): `e2e/keyboard-flows.spec.ts` drives sign up, sign in/out, create voice by file (real file chooser opened with Space), create by recording (start, stop, preview), generate, history replay, delete voice and delete account using Tab and key presses only, asserting a visible outline on every control it reaches and `aria-current` on the nav. 3/3 on Chromium and Firefox against the real backend; negative control: requiring a `dotted` outline fails it. Not run on WebKit |
| 3 | Manual NVDA and VoiceOver pass | **Not done** | needs a person |
| 4 | 44 px targets, 320 px and 400% reflow, forced-colors | **Met** | Re-run: `responsive` e2e (targets, reflow, long email at 320 px); forced-colors per log (FE-UX14) |
| 5 | Layouts at 320/375/768/1280/1920, baselines committed | **Met** | FE-UX34 (`33e3699`): `responsive` e2e now covers 320/768/1280/1920 (no horizontal scroll, 44 px targets, every public and signed-in route; real backend); 72 baselines at 375/768/1280/1920, light and dark, 104/104 visual tests pass; the 1920 px renders were viewed (content stays in the 5xl column, left-aligned; the footer line is centred, as at other widths). 320 px has no baseline image, only the `responsive` assertions |
| 6 | Chromium and Firefox e2e green; Safari tested or listed | **Met, Safari partial** | Re-run: full suite, **81 passed, 9 skipped (Chromium-only layout-shift specs on Firefox), 0 failed**. WebKit: mocked smoke 16/16, real e2e over HTTPS passes or skips on purpose (FE-UX27/29). Real Safari on macOS/iOS: not run |
| 7 | Every component has the §4.7 states, no disabled control without a reason | **Partial** | the reason pattern is tested for Generate and Voices; an exhaustive state-by-component audit was not done |
| 8 | Every UR10 status code, offline, mic denial, playback failure, expired audio tested | **Met per log** | FE-UX8/9/13 and the `resilience` e2e (re-run, passes); not re-audited code by code |
| 9 | Reduced motion: no animation | **Met per log** | FE-UX12 e2e; the `a11y`/visual runs use reduced motion |
| 10 | No hardcoded colour or one-off radius; no gradient, shadow, ALL-CAPS, numbered non-sequence | **Met (automated part)** | FE-UX32 (`0f42bfc`): `tests/theme.test.ts` now fails on shadows, blur, gradients, `uppercase`/`lowercase`/`capitalize` and any radius other than `rounded`, `rounded-lg`, `rounded-full` (negative control run). A numbered non-sequence is still a review item; the radii are Tailwind defaults (4/8 px), not the 6/10 px of §4.4 |
| 11 | Perf budgets, no soak leak | **Met, margin gone** | Re-run (`npm run perf`): LCP 1.96-2.27 s, CLS 0.001, TBT <= 15 ms, JS 181-200 KB; `/login` is **199.9 KB against the 200 KB budget (0.1 KB headroom)**; `soak` e2e passes |
| 12 | All suites zero failures; log updated | **Partial** | Re-run: unit 459, e2e 81/0 failed, visual 54, Lighthouse gate. Not run: `npm run smoke` (needs a deployed target). The CI `visual` job has never run |

**Reading it:** nothing is failing. One item is not yet fully evidenced (7), one needs a person (3), and two carry a risk to watch: the `/login` JS budget (any new code on a public route will break the gate) and real Safari.

---

## 10. Backend dependencies and open questions

### Backend dependencies
**None are required** for the phases above. Optional improvements that would raise quality:

| ID | Ask | Improves |
|---|---|---|
| UBD-1 | Stable machine `code` in error bodies and `Retry-After` on "busy" responses (the engineering plan's open BD-3) | UR10: replaces the string-matching table in `lib/errors.ts` (UX-13/UR3 copy accuracy; countdowns in UX-08) |
| UBD-2 | Publish the terms page URL (`GET /terms` returns `url: null` today) | the consent sentence (UX-13) can link to the real terms; the "not published yet" line disappears |
| UBD-3 | Optionally return sample quality/duration on `POST /voice/upload` | lets the Voices screen say "12 s of speech detected" and warn on weak samples (Proposal; not required) |

### Open questions (need the owner)
| ID | Question | Why it matters |
|---|---|---|
| OQ-1 | ~~Is there a brand colour or logo?~~ **Resolved, §11.1** | `signal` is the single swap point; today's teal is a Proposal derived from contrast and tone, not a brand |
| OQ-2 | ~~Rename `/dashboard` → `/studio` and split `/profile`?~~ **Resolved, §11.2** (split yes; the new name is `Generate`, not `Studio`) | U1 touches routes, e2e, smoke, RUNBOOK and any emailed links |
| OQ-3 | ~~Publish "clips are kept 30 days" on the landing page?~~ **Resolved, §11.3** (no) | it must match `OUTPUT_RETENTION_DAYS` and legal intent; the frontend cites it from `components/history-list.tsx:49` |
| OQ-4 | ~~Is an example voice needed, and whose?~~ **Resolved, §11.4** | without one the plan omits audio demos rather than faking them |
| OQ-5 | ~~Light/dark toggle?~~ **Resolved and implemented, §11.5** | U0.1 reserves the slot (UX-24) |
| OQ-6 | ~~Are IBM Plex fonts acceptable?~~ **Resolved and implemented, §11.6** | U0.2 |

### Unverified
1. All visual findings other than the three viewed screenshots are code-derived; 17 captured images were not individually inspected (§1).
2. Behaviour that needs a real backend or real audio: a successful generation, the upload progress bar, an open delete dialog, real recording.
3. Test files were not re-read; statements about which tests need updating are Assumptions.
4. Contrast numbers are computed from tokens, not measured on rendered pixels.

---

## 11. Owner decisions (2026-10-08)

The owner has no brand colour or logo and asked for decisions on six points. Each section lists the options considered, the scenarios that decide between them, and the outcome. Evidence for facts about the backend is cited; anything else is labelled.

### 11.1 Brand: logo and colour (implemented)
**Decision:** a waveform mark, signal teal on warm paper, set in IBM Plex Sans.
- **Mark** (`frontend/components/logo.tsx`, favicon `frontend/app/icon.svg`): five rounded vertical bars that rise to a peak and then fade out. The fading bars are the "clone" echoing the original. It reads as audio at 16 px, uses one colour (so it works in both themes and in one-colour print), and has no literal microphone or speech bubble.
- **Colour:** `signal` teal (`#0B6E69` light, `#5CC9BF` dark) on paper-neutral backgrounds. Teal is calm and trust-oriented, avoids the red of recording/danger and the default blue/indigo of generic SaaS, and passes contrast in both themes (§4.2, asserted in tests).
- **Rejected:** a microphone or speech-bubble icon (clichéd, reads as chat); a gradient or neon mark (the generic look the audit warns against, UX-11); a custom lettered monogram (illegible at favicon size).
- **Assumption / not done:** no trademark or name-collision search was performed on "CloneVoice"; do one before public launch. The mark is original but has not been legally reviewed.
- **Swap point:** if a designer supplies a brand later, change the `--primary` pair in `app/globals.css` and the fill in `app/icon.svg`; nothing else hard-codes the colour (a test enforces it).

### 11.2 Rename `/dashboard` and split `/profile`: decision
**Options:** A) change nav labels only; B) split `/profile` into `/voices`, `/history`, `/account` and keep `/dashboard`; C) split and rename the generator route; D) leave as is.

| Scenario | A labels only | B split | C split + rename | D as is |
|---|---|---|---|---|
| New user must find where to create a voice (UX-05/06) | partly: label fixed, page still four jobs | solved | solved | fails |
| One long scroll mixing create, list, history, delete-account | unchanged | solved | solved | unchanged |
| Deep links and bookmarks | safe | `/profile` needs a redirect | `/profile` and `/dashboard` need redirects | safe |
| Emailed links (`/verify-email`, `/reset-password`) | unaffected | unaffected | unaffected | unaffected |
| Google sign-in return and `next=` default | unaffected | unaffected | must change: `components/google-callback.tsx:18`, `components/signup-form.tsx:30,44`, `lib/auth/next-path.ts:1`, `components/verify-email-view.tsx:51`, `components/voice-profile-list.tsx:159`, `components/user-menu.tsx:39` | unaffected |
| Test and doc churn | none | about 25 test files reference `/profile` or the voice routes (grep) | the above plus about 20 files referencing `/dashboard` (e2e, unit, smoke, README, RUNBOOK) | none |
| Risk of a regression | lowest | medium | medium, mechanical | none |

**Decision: C, with a different name than I first proposed.** Split `/profile` into three routes (the real information-architecture defect: four jobs on one page, and a page titled "Your account" whose H1 is "Create a voice"). Rename the generator to **Generate** at `/generate`, not "Studio". Reasons: (1) the nav is a list of places the user goes to *do* something, and "Generate" names the one thing the page does, whereas "Studio" is a metaphor the user must decode and could imply recording, which lives under Voices; (2) the product principle in §4.8 is "say what happened and what to do next in plain words"; (3) the churn is mechanical, bounded (7 code references plus tests) and removed by 308 redirects for old URLs. If the owner prefers to minimise risk for a first release, B is the safe fallback (split only); A and D leave UX-05 and UX-06 unresolved.
**Not implemented in FE-UX0:** this is phase U1 (§7). Nav labels become Generate · Voices · History · Account.

### 11.3 "Clips are kept 30 days" on the landing page: decision (do not publish it)
**What the backend actually does (cited):**
- Generated WAV files expire after `OUTPUT_RETENTION_DAYS` (default 30; `0` or negative means forever), then the file is pruned and the history row stays (`backend/core/config.py:186-191`, `backend/services/storage_cleanup.py:35-100`).
- The uploaded **sample** and the **speaker embedding** are *protected from pruning* while the voice exists (`backend/services/storage_cleanup.py:35-45`, docstring lines 40-41): they are kept until the user deletes the voice. Deleting a voice or the account removes the audio, embeddings and generated outputs from disk immediately (`backend/services/erasure.py:1-10`).
- The value is an environment setting, not a constant.

| Scenario | Effect of publishing "clips are kept 30 days" |
|---|---|
| Reader means the voice sample they upload | **Wrong**: the sample is kept until deleted. The most privacy-sensitive data would be described inaccurately, in the wrong direction (kept longer than promised) |
| Reader means generated audio | Accurate today, but only for the default setting |
| Operator changes `OUTPUT_RETENTION_DAYS` (or sets it to 0) | The public promise becomes false without any code change; hard-coded copy cannot track a server setting |
| A privacy complaint or regulator reads the page | A specific retention figure on a marketing page is a commitment; no published terms or privacy page exists yet (`terms.url` is `null`, plan G-18) |
| Trust impact | A vague number the product does not control reads as filler (UX-04) |

**Decision:** do not put a retention figure on the landing page. Publish only statements that are true by construction and cite their source:
1. "You need the right to use a voice before you can clone it": consent is required at upload (`backend/api/voice.py:121-130`).
2. "Delete a voice and everything made with it is erased": `backend/services/erasure.py:1-10`.
3. "Generated speech is labelled as AI-generated in the app" (footer and result label, `components/app-shell.tsx:40`, `components/text-to-speech-form.tsx:239`). Wording says "in the app" because the audio file itself carries no watermark (Assumption: none found in the files reviewed).
**Follow-up (new, UBD-4):** show retention only in-app, next to History, driven by the server. Ask: expose `output_retention_days` on `GET /terms` (or a small config endpoint). Until then the existing hard-coded "kept for 30 days" text in `frontend/components/history-list.tsx:49` carries the same drift risk and is flagged for the first U2 change. Also state plainly on the Voices screen that samples are kept until the voice is deleted.

### 11.4 Example voice: is one required, and whose?
**For development: not required.** The repo already ships a test sample (`backend/tests/fixtures/sample_5sec.wav`, used by `frontend/e2e/helpers.ts:6`), and unit/integration tests use mocks. Manual quality checks can use your own recording locally; `uploads/` and `outputs/` are gitignored, so it never enters the repo.
**For a landing-page demo: optional, and deferred.** Options:

| Source | Consent and licence | Honesty | Practical risk | Verdict |
|---|---|---|---|---|
| **Your own voice** | Clear: you consent | Honest if the demo is output from this app | Publishing a clone of your own voice makes it reproducible by anyone who downloads it, the exact misuse the product warns about | Acceptable for private testing; **not recommended** as a public demo |
| **ElevenLabs (or any external TTS API)** | Output licensing depends on their plan and terms (Assumption: not verified; read them before any use). Using their voice as the *input* sample for this app's cloning model adds a second rights question | **Misleading**: the audio would be a competitor's quality, not what this model produces | Terms, cost, and a demo that over-promises | **Do not use** |
| **Public-domain or openly licensed corpus** (for example LJ Speech, a public-domain single-speaker corpus; LibriVox recordings; Common Voice, CC0) | Licence is explicit (Assumption: verify the exact licence of the specific file before use) | Honest if the output is generated by *this* app from that sample | Quality of this SV2TTS model is modest; a candid demo sets honest expectations | **Preferred, if a demo is wanted** |
| No demo | n/a | n/a | Landing page relies on text | **Default for now** |

**Decision:** no example voice is needed to proceed. When a demo is wanted, generate it with this app from a public-domain or openly licensed sample (clearly credited as such) and label it "AI-generated with CloneVoice". Never use an external TTS vendor's audio as a stand-in. Until then the landing page uses no audio (consistent with §5.3).

### 11.5 Light/dark toggle (implemented)
**Options considered:** (a) two-state toggle; (b) three-state System/Light/Dark; (c) storage in `localStorage` with an inline pre-paint script; (d) storage in a first-party cookie read on the server.
- **Mode model: three-state.** Two-state forces a choice and cannot return to "follow my OS"; people who switch OS theme by time of day need System. Default is System.
- **Storage: a first-party `cv-theme` cookie** (`frontend/lib/theme.ts`), read in the root layout (`frontend/app/layout.tsx`) so `<html data-theme>` is correct in the first byte. This avoids the flash of the wrong theme *without an inline script*, which the nonce-based CSP (`middleware.ts`) would otherwise need (and a script nonce would then have to be threaded into the layout). System is represented by the absence of the cookie and attribute, and is resolved in pure CSS (`prefers-color-scheme`), so System also never flashes. The cookie holds only `light`/`dark`, is `SameSite=Lax`, `Secure` on https and 1 year; anything else in the cookie is ignored (tested with a hostile value).
- **Guardrail change:** `tests/hardening.test.ts` forbade `document.cookie` anywhere to keep the access token memory-only (Definition of Done 5). It now allows exactly one file, `lib/theme.ts`, and asserts that file writes a single cookie, never touches storage, and never mentions tokens, passwords or emails.
- **Colour grading:** one token set per theme (§4.2); `color-scheme` is set per theme so native controls (select popups, scrollbars, file input, `<audio>`) match; dark mode is a neutral, slightly green-tinted near-black with desaturated accent, avoiding a pure `#000` background and a saturated neon. Contrast for every pair is asserted from the shipped values.
- **Transition:** a single 200 ms cross-fade of background, text, border and icon colours, applied by adding a class to `<html>` for 250 ms *only when the user switches* (so ordinary hover and focus never animate and there is no animation at page load). Under `prefers-reduced-motion` the theme switches instantly.
- **UI:** one 44 px icon button in the header that cycles System → Light → Dark; the icon shows the *selected mode* (monitor, sun, moon), so System is never mistaken for what the OS currently resolves to. It has an accessible name that states the current and the next mode, and a polite live region announces the change. `<meta name="theme-color">` follows the effective theme so mobile browser chrome matches.
- **Verified (real Chromium, API mocked):** OS-dark with no cookie renders dark; clicking cycles light → dark → system with the cookie set and cleared as expected; an explicit light choice survives a reload while the OS is dark; with JavaScript disabled a `cv-theme=dark` cookie still renders dark; no console errors; no horizontal overflow at 320, 375 and 1280 px; header height unchanged by toggling; reduced motion adds no transition class.
- **Not done:** a manual NVDA/VoiceOver pass; Safari/WebKit; the theme toggle on the pages that use their own `<html>` (the global error fallback, `app/global-error.tsx`, follows the OS only).

### 11.6 Font and styling (implemented)
**Criteria:** legible at 14-16 px; tabular figures and a matching mono face (the product shows times and sizes); open licence and self-hosting (CSP `font-src 'self'`, no third-party request); a distinct, calm character suited to a trust-heavy audio tool; small payload.

| Option | Strengths | Weaknesses | Verdict |
|---|---|---|---|
| System font stack | zero bytes, no CLS | inconsistent per OS, no identity, no matching mono | fallback only |
| Inter | excellent screen legibility | the ubiquitous default of generic SaaS and AI products | rejected for identity |
| Geist / DM Sans / Manrope | modern geometric | strongly associated with startup templates; geometric forms can feel cold for a trust tool | rejected |
| Source Sans 3 | very legible, variable | plain; no mono sibling with the same design | viable second choice |
| Serif display (Fraunces etc.) | warmth | trendy, harder at small sizes in a form-heavy UI | rejected |
| **IBM Plex Sans + IBM Plex Mono** | humanist-technical character that suits audio and engineering, clear numerals, true mono sibling for timecodes, SIL OFL licence | slightly wider than Inter | **chosen** |

**Implemented** (`frontend/app/layout.tsx`, `frontend/app/fonts/`): Plex Sans 400/500/600 and Plex Mono 400, Latin subset, self-hosted with `next/font/local` (`display: swap`, automatic size-adjusted fallback so swapping does not shift layout), licence file included. Mono loads only on pages that use it (`preload: false`) and is applied to the character counter and the recording clock with `tabular-nums`. Styling follows §4.4-§4.8: flat surfaces, hairline dividers, one accent, a single visible `focus-visible` ring, no shadows or gradients.
**Measured cost** (Lighthouse, median of 5, public routes, local): LCP 2.1-2.3 s (it was 1.8-2.0 s before the fonts, `FRONTEND_IMPLEMENTATION_PLAN.md` FE-P7l), JS 178-194 KB (within 200 KB; about +1 KB), CLS 0.000. All within budget; the LCP margin to the 2.5 s limit is now about 0.2-0.4 s, so watch the first CI run. If it flaps, first drop the 500 weight (use 400/600), then raise `PERF_RUNS`.
