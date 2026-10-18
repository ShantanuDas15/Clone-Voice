# CloneVoice — Chatterbox Engine Rollout Plan

> **Status**: 📝 Planned, nothing started. **Last Reviewed**: 2026-10-18
> **Scope**: put a Chatterbox engine in front of real users, behind a canary, with SV2TTS as the fallback and kill switch. This is a rollout plan; the engine, worker, fallback, canary, metrics, watermark and per-engine rate limit are already built and merged (`SPEECH_QUALITY_PLAN.md` S4.3, S4.4, S7.1–S7.4). What is missing is decisions, a deployed worker, evidence from real listeners, and a runbook.
> **Rule**: backend and rollout work follow CLAUDE.md §3 (branch, tests, PR). Nothing in this plan changes the default `TTS_ENGINE=sv2tts` until the go/no-go in §6.

## 1. Where things stand (verified 2026-10-18 from the repo, not re-measured)

| Area | State |
|---|---|
| Default engine | `TTS_ENGINE=sv2tts` (pretrained Tacotron 2 + WaveRNN, 16 kHz). Unchanged by any milestone. Baseline: similarity 0.76, median pitch error 3.4 semitones. |
| Chatterbox benchmark (S4.2a/b; 6 speakers x 10 texts, one seed) | Original: similarity 0.869, WER 0.017. Turbo / Nano: similarity 0.856 / 0.856, WER 0.003 / 0.005. SV2TTS: 0.763, WER 0.178. 24 kHz output. Judged by SV2TTS's own encoder (conservative, not independent). |
| Speed / memory | GPU RTF 0.56 (original), 0.25 (Turbo), 0.12 (Nano). **Nano on CPU: RTF 0.76 at 8 threads, 4.3 GiB** (SV2TTS CPU RTF 1.88, 1.6 GiB). Original on CPU: not viable (RTF 6.5, 6.7 GiB). |
| What each variant can do | Original: `exaggeration` (loudness-like intensity; the only emotion control built). Turbo and Nano: `[laugh]`, `[chuckle]`, `[cough]` sound tags; ignore `exaggeration`. None has labelled happy/sad/angry. |
| Built | `tts_worker/` service (token before body, one at a time, stateless, PerTh watermark on), `ChatterboxEngine` client, SV2TTS fallback + circuit breaker, per-user canary (`TTS_CANARY_ENGINE`, `TTS_CANARY_PERCENT`), per-engine RTF/outcome/fallback metrics, per-engine rate limit, AudioSeal watermark, engine recorded per generation and shown in the UI. |
| Not done | Worker image never built (CI does not build it); fallback never tested against a lossy network; no host chosen; **no listening test, MOS, independent similarity judge, or child/elderly voices**; consent text does not mention a separate service receiving recordings; training data undisclosed. |

## 2. Findings that shape the plan

1. **Quality gain is real but measured with a flattering judge.** Similarity +0.09 and WER 0.178 → ~0.005 are large; the judge is the same encoder family SV2TTS conditions on, so the true gain is probably *larger* for similarity but unknown for naturalness (no MOS).
2. **Nano is the only variant that runs acceptably without a GPU, and Nano ≈ Turbo ≈ 0.014 below the original on similarity.** The original is only worth its GPU for the `exaggeration` control, which is intensity-only and unheard.
3. **The app refuses a plain-`http` worker URL unless it is localhost** (`worker_engine_is_configured`, `core/config.py`), because voice recordings travel to it. Railway's private network address (`http://<service>.railway.internal`) is, as I recall, plain http (**unverified: check Railway's docs**), so it would be rejected at startup. Options in §3, decision D3.
4. **Recordings leave the app process.** The worker receives each request's reference clip. That is a new data flow the consent/terms text does not describe (`tts_worker/README.md`, S4.3 open item 3; `lib/terms-content.ts` has no mention).
5. **Stored samples are required and protected:** Chatterbox reads the profile's stored first clip; `get_protected_paths` keeps samples of non-deleted profiles from age pruning. Profiles are engine-neutral, so no data migration is needed to switch.
6. **Training data is undisclosed** (stated "0.5M hours"); risk R1 (licence) was cleared for the MIT code and weights only. An owner decision, not an engineering one.

## 3. Decisions the owner must make

| # | Decision | Options | Recommendation |
|---|---|---|---|
| **D1** | Accept the model's undisclosed training data and its licence terms for commercial use? | Accept / reject (stay on S1–S3 only) | Yours. If rejected, this plan stops at §6 "no-go" and the work stays as a documented option. |
| **D2** | Which variant, and what hosting | **A.** Nano on CPU, a second Railway service (same provider, no GPU). **B.** Original or Turbo on a serverless GPU provider (pay per second, cold starts). **C.** Always-on GPU VM. | **A first.** Same quality tier as Turbo, no GPU, no new provider, simplest data path. Revisit **B** only if you want `exaggeration` (original only) after a listening test shows it matters. C costs the most for no benefit at this scale. Railway limits and prices must be checked against their docs (my earlier figures were from memory). |
| **D3** | How the app reaches the worker | **a.** Worker gets a public https domain; token + TLS protect it. **b.** Private network, and extend the validator to accept `*.railway.internal` over http (a reviewed, narrow allow-list). | **b** if the worker is on Railway (traffic never leaves the private network; smaller attack surface), implemented as an explicit `TTS_WORKER_ALLOW_PRIVATE_HTTP` host-suffix setting with tests, **not** by loosening the check generally. **a** if the host is another provider. |
| **D4** | Consent wording | Add to the terms: recordings are processed by a separate speech service operated by us; sound tags/non-speech sounds are generated in the user's voice | Needs your or counsel's text; I draft, you approve; bump `TERMS_VERSION` (a client that showed the old terms gets a 409 "terms changed" at its next upload, RU-3; existing voices keep the version they were created under, so decide whether existing users must be told by other means). |

## 4. Phases

### R0 — Prerequisites (no users involved)
| Task | Work | Done when |
|---|---|---|
| R0.1 | **Build the worker image in CI** (`docker build tts_worker/` job, like `docker-build.yml` for the backend) and smoke-test `/health` and one synthesis with the stub path | CI job green; image runs |
| R0.2 | If D3=b: narrow private-network allow-list in `Settings` + tests (accepts `x.railway.internal` over http, still rejects any other plain-http host; token still required) | tests incl. boundary hosts (`evilrailway.internal`, `railway.internal.evil.com`) |
| R0.3 | Draft the consent/terms text (D4); bump `TERMS_VERSION`; frontend terms page; tests | You approved the text |
| R0.4 | Runbook `CHATTERBOX_RUNBOOK.md`: env vars, how to flip, how to roll back, what to watch | reviewed |

### R1 — Stand up the worker (staging, no user traffic)
1. Deploy worker as its own service (model `nano`, `TTS_WORKER_DEVICE=cpu`, `OMP_NUM_THREADS` = real cores, one replica), secrets via env, health check on `/health`.
2. Point a **staging** app at it (`TTS_ENGINE=chatterbox_nano`).
3. **Measure on the real host** (the plan's own budget, SPEECH_QUALITY_PLAN §9): RTF at the maximum text length against `INFERENCE_CALL_TIMEOUT_SECONDS` (30 s) and `TTS_WORKER_TIMEOUT_SECONDS` (25 s); memory against the container limit; cold start time (first request after deploy; set a readiness/warm-up policy); queue behaviour under 3 concurrent users (one at a time, two waiting, then 503 → fallback).
4. **Fallback drills**: kill the worker; return 5xx; add network loss/latency (e.g. `tc netem`); wrong token; confirm users get SV2TTS audio, `X-Voice-Engine-Fallback` is set, the breaker opens after 3 and recovers after the probe.
5. Re-run `python -m backend.measure_event_loop_lag` (app side, must still hold) .
**Go to R2 only if:** max-length text finishes inside both timeouts with headroom ≥ 30 %, memory ≤ 80 % of the limit, fallback drills pass, no recording or text found in the worker's logs.

### R2 — Evidence from people (the missing gate)
1. **Corpus**: the S0 set (20 LibriSpeech speakers) **plus** children and elderly voices (consented volunteers; guardian consent for children, per the 2026-10-10 decision) — minimum 4 volunteer speakers of your choosing, since LibriSpeech has none.
2. **Blind A/B listening test**: for each speaker and 6 texts (plain, numbers, questions/exclamations, a long paragraph), play SV2TTS vs Nano (order randomised, unlabelled). Raters (you plus 4–5 others, minimum 5 raters): score naturalness 1–5 and "sounds like the speaker" 1–5. Tooling: a small script in the scratchpad that serves paired clips and writes a CSV; I build it, you and the raters do the listening.
3. **Independent similarity**: score with a second encoder (ECAPA or similar; scratch install, not a runtime dependency) so the judge is not SV2TTS's own.
4. Optional, only if D2 is revisited: the same test for original + `exaggeration` vs Nano, to decide whether the GPU tier is worth it.
**Go / no-go thresholds (proposed, adjust before the test, not after):** Nano preferred over SV2TTS on naturalness by a clear majority (≥ 65 % of paired votes, paired mean ≥ +0.5 on the 5-point scale), speaker likeness not worse than SV2TTS (paired mean ≥ 0), independent similarity not worse for any speaker group (child/elderly/male/female gap no larger than SV2TTS's), WER ≤ SV2TTS. A **miss on children/elderly means they stay on SV2TTS** (a per-profile routing task, not a blocker for the rest) — decide after seeing data.

### R3 — Canary on real users
Ramp with `TTS_CANARY_ENGINE=chatterbox_nano`, `TTS_CANARY_PERCENT`; users are placed by a stable hash, so a user never flips engines and raising the percentage only adds users. Hold each step at least 48 hours and at least ~100 syntheses on the canary before moving on.

| Step | Percent | Advance only if (from `/metrics`; per engine) |
|---|---|---|
| 1 | 5 % | `clonevoice_engine_synthesis_total{outcome="unavailable"}` < 2 % of canary requests; fallback rate (`clonevoice_engine_fallback_total`) < 5 %; gate refusals (`gate_refused`) no worse than SV2TTS; p95 `clonevoice_engine_rtf` within budget; zero 5xx from the worker not covered by fallback |
| 2 | 25 % | same, plus no rise in failed generations or support complaints |
| 3 | 50 % | same |
| 4 | 100 % via `TTS_ENGINE=chatterbox_nano` (canary back to 0, SV2TTS stays the fallback) | stable for a week |

**Rollback (config only, no deploy):** `TTS_CANARY_PERCENT=0` (canary) or `TTS_ENGINE=sv2tts` (kill switch). A worker outage already degrades to SV2TTS by itself; rollback is for *quality* problems.
**Rate limit:** set `SYNTHESIZE_RATE_LIMIT_BY_ENGINE` for `chatterbox_nano` from the measured RTF (a slow engine must not let one user queue the single worker); review cost per synthesis.

### R4 — After rollout
Remove nothing: keep SV2TTS as the fallback (`TTS_FALLBACK_ENGINE=sv2tts`). Re-run the S0 study on the live engine and record the real numbers in `SPEECH_QUALITY_STUDY.md`; close S4.2/S4.3/S4.4/S7.4 "Partial" rows only where measured.

## 5. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Worker is a single point of slowness (one request at a time) | Bounded queue → 503 → SV2TTS fallback; per-engine rate limit; alert on fallback rate; scale by a bigger instance, not replicas, until a queue is needed |
| Nano memory (4.3 GiB) exceeds the host limit | Measured in R1.3 before any traffic; fall back to a larger instance or stop |
| Recordings reach a service users were not told about | D4 consent text + `TERMS_VERSION` bump before R3; TLS or private network only (R0.2); worker is stateless and does not log text/audio (tested) |
| Quality is worse for some groups (children, elderly) | R2 includes them; routing them to SV2TTS is an allowed outcome |
| Gain is smaller than the benchmark suggests | R2 thresholds decide; "no-go" is a valid result and the work stays as an option |
| Undisclosed training data / licence | D1; nothing ships without it |
| Dependencies pinned to Git commits, lock without hashes | Accepted risk recorded; image built in CI from the lock; revisit when upstream publishes Nano to PyPI |
| Silent truncation of long text (model caps ~40 s of speech) | The gate's duration check; R1.3 tests the maximum length; keep the 500-character limit |

## 6. Go / no-go summary

Ship (R3) only when **D1 accepted** and D4 text live, **R1 gates pass**, and **R2 thresholds met**. Otherwise record "no-go" in `SPEECH_QUALITY_PLAN.md` S4.2/S4.3 and stay on the S1–S3 improvements (text handling, multi-clip profiles); nothing already merged needs to be undone, since the default is unchanged.

## 7. What I can do without you vs what needs you

| I can do now | Needs you |
|---|---|
| R0.1 CI image build, R0.2 allow-list, R0.4 runbook, R2 listening-test tooling and the independent-encoder scoring, R1 measurement scripts | D1–D4; a Railway project (and its plan/limits); volunteer speakers incl. children/elderly; the listening itself; the real production secrets |

## 8. Milestone tracker

| Milestone | Status | Commit |
|---|---|---|
| R0.1 worker image in CI | ⬜ Not started | — |
| R0.2 private-network allow-list (if D3=b) | ⬜ Not started | — |
| R0.3 consent/terms text | ⬜ Needs D4 | — |
| R0.4 runbook | ⬜ Not started | — |
| R1 worker on staging + measurements + fallback drills | ⬜ Needs D2 | — |
| R2 listening test + independent similarity | ⬜ Needs speakers and raters | — |
| R3 canary ramp | ⬜ Blocked on R1, R2, D1, D4 | — |
| R4 post-rollout study | ⬜ | — |
