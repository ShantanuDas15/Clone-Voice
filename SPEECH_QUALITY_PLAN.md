# CloneVoice — Speech Quality & Expressiveness Improvement Plan

> **Status**: 🟡 In Progress (0 of 8 Phases complete; S0.1 to S0.4, S1.1 to S1.4 and S2.1a landed in part, S1 measured, see §5.1)
> **Scope**: Backend speech pipeline — make cloned voices closer to the real speaker and make the
> speech react to the text (punctuation, emotion, emphasis). Frontend work is listed per phase but
> starts only after the backend gate (CLAUDE.md §2).
> **Last Reviewed**: 2026-10-11 (S2.1a landed; S0.1 to S0.4, S1.1 to S1.4 landed in part; S1 measured 2026-10-11) · **Decisions Q1–Q3 recorded** (§7)
> **Source of truth for baseline**: `backend/services/tts_pipeline.py`, `text_chunking.py`,
> `audio_processing.py`, `sv2tts/`, `PREPROCESSING_STUDY.md`, `HARDENING_PLAN.md`.

---

## 1. Honest framing

"Perfect, human-like replication" is not a testable target, and no current system reaches it.
This plan replaces it with **measured targets** (§4). Each phase must move a number, or it is not done.

Two separate problems, with different fixes:

| Problem | What the user hears | Root cause (in this repo) |
|---|---|---|
| **Voice fidelity** | "Sounds like a different person" / robotic, band-limited | 16 kHz audio, WaveRNN vocoder, one 256-d embedding from a general speaker-verification encoder |
| **Expressiveness** | `!` and `?` sound the same as `.`; no anger, sadness or joy | The model has no input for emotion, and was trained on neutral read audiobook speech |

Fidelity can be improved incrementally. Expressiveness **cannot** be fixed with text-processing tricks
on the current Tacotron 2 checkpoint; it needs a model that accepts style/emotion conditioning
(Phase 4–5). Phases 1–3 are worth doing first because they are cheap, low-risk and give a measurable
baseline.

---

## 2. Baseline audit (what the code does today)

| Stage | Current behaviour | File | Limitation |
|---|---|---|---|
| Request | `text` 1–500 chars, charset check against the symbol set | `schemas/synthesize.py` | No `emotion`/`style` field. (Audit correction, 2026-10-10: `…`, `—` and curly quotes were already accepted, because `unidecode` maps them to `...`, `--` and straight quotes; what was rejected was `$ % & @ # + = / *`, emoji and `[ ]`.) |
| Text cleaning | `english_cleaners`: transliterate, **lowercase**, expand numbers/abbreviations | `sv2tts/synthesizer/utils/cleaners.py` | Lowercasing throws away emphasis (`I said NO`). No acronym, currency or date handling beyond numbers |
| Chunking | Split at `. ! ? ; :` + newline, merge up to 150 chars, fixed 0.15 s pause | `text_chunking.py`, `TTS_CHUNK_PAUSE_SECONDS` | Pause is the same after a comma-clause, a full stop, a `?` and a `!`. Merged sentences lose their individual intonation. Chunks are synthesized independently, so pitch resets at every boundary |
| Speaker identity | `resemblyzer` `VoiceEncoder`, one 256-d vector from one clip | `embed_speaker()` | One clip, no quality scoring, no multi-clip averaging. Encoder is trained for verification, not for capturing timbre or speaking style |
| Acoustic model | Tacotron 2, `reduction=2`, 80 mel, LSTM decoder, stop-token, **max 900 frames** | `sv2tts/synthesizer/models/tacotron.py` | No emotion/style input. Autoregressive (word skipping, repeats on long input). Neutral prosody |
| Vocoder | WaveRNN (mu-law, 9-bit), **16 kHz** | `sv2tts/vocoder/` | Hard 8 kHz bandwidth cap — audibly "telephone-like"; slow on CPU (see `PREPROCESSING_STUDY.md` timings) |
| Output | Raw vocoder output, clipped to ±1, 16-bit WAV | `save_output()` | No loudness normalisation, no de-noise/de-click, no quality gate |
| Sampling | Stochastic (dropout active at inference per reference design) | `_synthesize_chunk()` | Same text gives different quality each time; no re-ranking |
| Evaluation | Only the **preprocessing** study (speaker similarity, LibriSpeech) | `evaluate_preprocessing.py` | No intelligibility, no naturalness, no emotion metric |
| Runtime | `DEVICE=cpu` in deployment (Railway has no GPU); dev machine has an RTX 4060 | `core/config.py`, `RAILWAY_DEPLOYMENT.md` | Any heavier model must still run acceptably on CPU or the deployment target changes |

Measured so far: cloned-voice speaker similarity ≈ **0.85** (resemblyzer cosine, LibriSpeech, clean
reference). That is a usable baseline, not a ceiling.

---

## 3. Guiding rules

1. **Measure first.** No model swap or tuning before Phase 0's harness exists and a baseline is recorded.
2. **One engine interface.** Every engine (current SV2TTS, any new one) sits behind `TTSEngine`, selected by a setting, with SV2TTS as the fallback. A bad rollout is a config change, not a revert.
3. **Backend before frontend** (CLAUDE.md §2); each milestone follows the SOP in CLAUDE.md §3 (branch, black/isort, zero-error pytest, conventional commit, PR into protected `main`).
4. **Consent and provenance stay.** Better cloning raises abuse risk. The consent gate, WAV provenance metadata and erasure on delete must keep working for every new engine; Phase 7 adds an inaudible watermark.
5. **No live services in tests** (CLAUDE.md §4.2). Heavy models are mocked in the unit suite; real-model checks live in an opt-in `evaluate_*.py` tool, like `evaluate_preprocessing.py`.
6. **Licences are a gate.** Several strong open TTS models carry non-commercial weights licences. Verify each in the Phase 4 decision record before adopting; do not assume.

---

## 4. Success metrics

Scored by `backend/evaluate_synthesis.py` (built in Phase 0) on a fixed, seeded test set. Targets are
proposals; Phase 0 confirms them against the real baseline.

| Metric | Measures | Tool | Baseline | Target |
|---|---|---|---|---|
| **SECS** — speaker-embedding cosine, clone vs real speaker | Voice likeness | A *different* encoder than the one that conditions the model (e.g. ECAPA-TDNN) so the model cannot "game" its own judge | measure (≈0.85 on resemblyzer) | ≥ +0.05 absolute |
| **WER / CER** of the output transcribed back | Intelligibility, skipped/repeated words | Whisper (small/medium), offline | measure | ≤ 5 % WER on the test set |
| **Predicted MOS** | Naturalness | UTMOS (or similar automatic predictor) | measure | ≥ 3.8 |
| **Emotion accuracy** | Does "angry" text sound angry | Speech-emotion classifier (e.g. emotion2vec) on output vs requested label | ≈ chance (no control exists) | ≥ 70 % on 4 classes (neutral / happy / sad / angry) |
| **Punctuation contrast** | `.` vs `?` vs `!` change the contour | F0 slope of last 300 ms (question), mean energy + F0 range (exclamation) vs the `.` version of the same sentence | ≈ 0 difference | `?` final-F0 rise on ≥ 80 % of pairs; `!` energy/F0 range above `.` on ≥ 80 % |
| **Per-group SECS** (adult M/F, child, elderly, pitch tails) | Fairness across voices | Same tool, stratified | measure | every group within 0.05 of the best group |
| **F0 error / range ratio / formant distance** | Pitch, depth, shrillness fidelity | Pitch tracker + long-term spectrum | measure | median F0 error ≤ 1 semitone; range ratio 0.8–1.2 |
| **Human listening test** | The real answer | ABX / MUSHRA, ≥ 10 listeners, blind, 20 sentences | none | New engine preferred over baseline ≥ 70 % |
| **Real-time factor (RTF)** on target hardware | Latency | `measure_*` scripts | measure (CPU) | Stated per phase; never silently worse than the budget in §9 |

Automatic metrics guide development; **only the listening test decides release.**

---

## 5. Progress tracker

| Phase | Name | Status | Commit | Completed |
|---|---|:---:|:---:|:---:|
| **S0** | Evaluation harness & baseline | 🟡 | `cd7ec07` (S0.1), `f4d8cbe` (S0.2), `12f2f1e` (S0.4), `4bc6470` (S0.1c) | — |
| **S1** | Text front-end & punctuation-aware prosody (current model) | 🟡 | `92b71c8` (S1.1, S1.4), `8a43fe0` (S1.2, S1.3) | — |
| **S2** | Voice-profile quality (embedding & enrollment) | 🟡 | `8fa74ae` (S2.1a) | — |
| **S3** | Vocoder & output polish | 🔴 | — | — |
| **S4** | Engine abstraction & expressive acoustic model | 🔴 | — | — |
| **S5** | Emotion & style control (text analysis → conditioning) | 🔴 | — | — |
| **S6** | Long-form, non-verbal expression & speaker adaptation | 🔴 | — | — |
| **S7** | API, frontend, safety, rollout | 🔴 | — | — |

**Legend**: 🔴 Not Started · 🟡 In Progress · 🟢 Complete · ❌ Blocked

Dependency order: S0 → (S1, S2, S3 in any order) → S4 → S5 → S6 → S7. S1–S3 improve the current
engine and keep paying off after S4 (S1 and S2 carry over; S3 is replaced if the new engine ships its
own vocoder).

### 5.1 Task Status Log

| Milestone | Status | Commit | Date | What was verified | What is still open |
|---|:---:|:---:|:---:|---|---|
| **S0.1** Metric library + study CLI (`backend/evaluate_synthesis.py`) | 🟡 Partial | `cd7ec07` | 2026-10-10 | 34 new unit/integration tests pass on synthetic signals with known answers (SECS, F0 error, F0 range ratio, spectrum distance, final-pitch slope, `?`/`!` contrast, WER/CER, bootstrap CI, per-group gap, dataset loading, orchestration with the model mocked). Full backend suite: **939 passed, 1 skipped, 11 warnings** (the 11 third-party warnings of the baseline; no new ones). CLI smoke-run against the **real** synthesizer/vocoder weights on a scratch tone reference: loads, runs 16 syntheses, writes the JSON report, leaves no files in `outputs/` (numbers from that run are meaningless: the reference was a tone, not speech) | (1) Independent speaker encoder (plan §4: SECS is currently judged by the same resemblyzer encoder that conditions the model, so it flatters the model); (2) ~~Whisper WER~~ (added in S0.1c), predicted MOS and emotion classifier; (3) **a real-speech baseline**: no speech data exists in the repo. Closed by S0.2 + S0.4: `python -m backend.evaluate_synthesis --data-dir <speakers/> --groups groups.json` on LibriSpeech plus child/elderly sets |
| **S0.1c** WER, pause profile and multi-sentence stimuli | 🟡 Partial | `4bc6470` | 2026-10-11 | `evaluate_synthesis.py` gains Whisper word error rate (faster-whisper `small.en`, optional, lazy import, not a runtime dependency), a pause profile (20 ms RMS frames; reads a gap within about 20 ms), `paragraph` and `typed` stimuli in the fixture (8 each), balanced speaker choice across groups and `--skip-single`. 15 new tests; 1097 passed, 1 skipped, 11 warnings (baseline). Real run, **before vs after Phase S1** on 10 balanced speakers (details in `SPEECH_QUALITY_STUDY.md`): **typed-text WER 0.384 to 0.095** (paired change -0.289, CI [-0.335, -0.245], 10 of 10 speakers better); audible pauses per paragraph 1.4 to 2.6, mean pause 0.23 s to 0.50 s; speaking time per word 0.27 s to 0.34 s (about 220 to 176 words per minute); plain-paragraph WER 0.116 to 0.070 (not significant, so no regression) | (1) Still no independent speaker encoder, predicted MOS, emotion classifier or RTF. (2) **No listening test**: ASR errors and pause counts are proxies. (3) Typed-text reference is defined by the new normaliser (intended words), which favours the new pipeline somewhat. (4) n = 5 per group, 4 paragraphs and 4 typed texts each, one seed, adults only. (5) `faster-whisper` is deliberately not in `requirements-dev.txt` (it would change the CI install and the lockfiles): install it with `pip install faster-whisper` to run the study |
| **S2.1a** Multi-clip embedding aggregation + evidence | 🟡 Partial | \`8fa74ae\` | 2026-10-11 | New \`services/voice_embedding.py\` (pure numpy): \`aggregate_embeddings\` (unit-length mean, order-independent, magnitude-independent, rejects empty/ragged/zero/non-finite/cancelling input), \`clip_agreement\` and \`find_outliers\` (a clip scored against the mean of the others; nothing is flagged below three clips). \`evaluate_synthesis --enroll-compare K\` compares one clip with K aggregated clips on the same held-out speech, paired seeds. 29 new tests; 1119 passed, 1 skipped, 11 warnings (baseline). **Measured on 20 real speakers** (details in \`SPEECH_QUALITY_STUDY.md\`): embedding closer to real speech **+0.052** (20 of 20 speakers); clone similarity **+0.025** [+0.008, +0.046] (14 of 20); group gap 0.046 to 0.033; **pitch error unchanged** (-0.24 semitones, CI spans zero). Same-speaker check at 0.75: 95.8% of other-speaker clips caught, 1.7% of true clips flagged | (1) **No database or API change yet (S2.1b)**: the upload still makes a single-clip profile; needs a \`voice_profile_samples\` table or column, an Alembic migration (also on real Postgres), multi-file upload, per-clip failure leaving no partial profile, and erasure of every stored sample. (2) The similarity gain is judged by the same encoder (flattered); an independent encoder is open. (3) **Finding that redirects effort**: aggregation does not reduce the pitch error, so that weakness belongs to the model (S3/S4) and adaptation (S6.4), not enrolment. (4) The 0.75 agreement threshold rests on 60 true clips; use it as a warning, not a control |
| **S1.2** Punctuation-aware segmentation | 🟢 Fixed | `8a43fe0` | 2026-10-10 | `text_chunking.split_into_segments` returns typed `Segment(text, boundary)`; `.`/`?`/`!`/`…`/`;:`/paragraph are told apart and only plain statements merge, so a `!` or `?` keeps its own decode. Found and fixed on the way: `english_cleaners` collapsed every newline before segmentation, so line/paragraph breaks never reached the segmenter (the old newline split only worked in its unit test); `_clean_for_chunking` now cleans line by line. The API now accepts `\n`/`\r` (it returned 422) so breaks are reachable | Measured since (S0.1c): audible pauses per paragraph 1.4 to 2.6, no intelligibility regression. Whether it *sounds* better still needs a blind listening test |
| **S1.3** Punctuation-aware pauses | 🟡 Partial | `8a43fe0` | 2026-10-10 | `TTS_PAUSE_SECONDS` (validated table, partial overrides, env-JSON) replaces `TTS_CHUNK_PAUSE_SECONDS`; pause follows the previous segment's ending: statement 0.40, question/exclamation 0.45, ellipsis 0.60, clause 0.25, paragraph 0.70, comma-cut 0.12, word-cut 0.05. 32 new tests (971 passed, 1 skipped, 11 warnings; baseline warnings only). Real weights: typed segments and gaps 0.40/0.45/0.45/0.70 s confirmed, audio finite, no 900-frame truncation | (1) The plan's **comma pause inside a chunk** is not done: it needs token-to-frame alignment inside Tacotron, and Tacotron already renders commas itself. Decide from S0 data. (2) The default values are the plan's proposals, **not tuned**: tune against listening tests. (3) Audio is now longer than before for multi-sentence text (0.15 s gaps became 0.40+ s); the 500-char limit and timeouts were checked by the suite only, not under real load. (4) Operators: `TTS_CHUNK_PAUSE_SECONDS` is silently ignored now. (5) **Measured since (S0.1c)**: mean pause 0.23 s to 0.50 s and pace 0.27 to 0.34 s per word; a 0.50 s mean may be long for some listeners, so tune by listening test |
| **S1.1** Text normalisation | 🟡 Partial | `92b71c8` | 2026-10-10 | New `services/text_normalization.py` (pure, English, table-driven, runs before the cleaners so it can use case): times (`10:30 PM`), `a.m.`/`p.m.`, ISO dates, fractions, units and `°C`, `% & @ # + = /`, emails and URLs read aloud, `e.g.`/`i.e.`/`etc.`/`vs.`, acronyms spelled by letter name (FBI, TV, HTML, CPUs) while words (NASA) and shouted words (NO, STOP, WHY) are left alone, dotted initials (`U.S.A.`). One `clean_text` is now used by both the pipeline and the request validator, so the API accepts exactly what the pipeline can say (`$4.50`, `50%`, `Tom & Jerry`, `me@x.com` were 422 before; emoji, `[ ]`, `{ }`, control chars still are). 90 new tests; 1061 passed, 1 skipped, 11 warnings (baseline). Real weights: the model receives `at ten thirty pee em the eff bee eye paid four dollars, fifty cents and said no!` for the test sentence | **Measured since (S0.1c)**: typed-text WER 0.384 to 0.095 on 10 speakers (all better). **Still no listening test**; the reference is the normaliser's own definition of the intended words. The spelled-letter names ("eff bee eye") are my choice and may need tuning. The acronym rule is a heuristic (listed acronyms + all-consonant caps; ambiguous words such as IT, WHO, US are never spelled). Not done: roman numerals, `10/10/2024` dates (ambiguous, deliberately not guessed), currency other than `$` and `£` (the existing number code), currency words after the amount |
| **S1.4** Wider input charset | 🟡 Partial | `92b71c8` | 2026-10-10 | `*emphasis*` is accepted and the markers removed; the validator change above covers the symbols. Audit correction recorded in §2 | The emphasis **hint is not recorded or used**: ALL-CAPS and `*stress*` are lowercased/stripped, so emphasis has no effect until S5. `[laugh]`-style tags stay rejected until S6.2 |
| **S0.2** Corpus & expressive sentence set | 🟡 Partial | `f4d8cbe` | 2026-10-10 | `backend/eval_data/expressive_sentences.json`: 40 groups (stem for `.`/`?`/`!` plus a neutral, happy, sad and angry sentence), every text accepted by the API validator. `backend/prepare_eval_corpus.py` builds the scratch corpus from LibriSpeech test-clean (CC BY 4.0; already cached locally): per speaker one 10-30 s reference and five held-out 3-20 s clips, plus `groups.json` and a provenance `manifest.json`. Run for real: **20 speakers, 10 `adult_low_f0` and 10 `adult_high_f0`** (median-F0 bands, split at 165 Hz; not gender labels: LibriSpeech has none in the parquet). The study CLI now reads the fixture (`--stems`, `--sentences`). 21 new tests; 1082 passed, 1 skipped, 11 warnings (baseline) | **No child or elderly speech**: no licensed source is verified yet. Candidates to check (access and licence are *not* confirmed): Mozilla Common Voice (CC0, has age and gender metadata, but its youngest age band is teens, not children), and child-speech corpora, which usually carry restrictive licences and consent duties. Until then every per-group result is adult-only and says nothing about children or the elderly. The emotion sentences are written for the emotion metric (S0.3), which does not exist yet |
| S0.3 Punctuation + emotion metrics | 🟡 Partial | `cd7ec07` | 2026-10-10 | Punctuation contrast (`?` final-pitch rise, `!` pitch range + energy) is implemented and tested; the CLI uses 5 built-in sentences | Emotion classifier metric; the full 40-sentence set (S0.2) |
| **S0.4** Baseline recorded in `SPEECH_QUALITY_STUDY.md` | 🟡 Partial | `12f2f1e` | 2026-10-10 | Real run, 20 LibriSpeech speakers (10 low-F0, 10 high-F0), 320 syntheses with the real weights, on the pipeline before S1 (`d9070cf`) and after (`f4d8cbe`): **all six metrics identical for all 20 speakers**, so the fixed-seed gate is met. Baseline: speaker similarity 0.760 (low 0.786, high 0.734; gap 0.051, just over the 0.05 limit), median pitch error 3.4 semitones (high voices 4.4; target 1), pitch range 0.68 of real (target 0.8 to 1.2), `!` lifts range and energy in 22% of pairs (target 80%), `?` rises at 52% (about chance) | (1) ~~The stimuli are single sentences, so the study cannot see S1~~: resolved by S0.1c (multi-sentence stimuli run on both checkouts). (2) Predicted MOS, emotion classifier, independent encoder and RTF are not in the baseline. (3) No children or elderly. (4) The `?` metric has no positive control on natural speech. (5) n = 10 per group: wide intervals. The section 4 targets are kept unchanged |

Method note: thresholds for the `?`/`!` contrast are deliberately **not** invented. `punctuation_contrast`
returns the raw deltas and a strict pass/fail (`?` ends higher; `!` has both a wider pitch range and more
energy), and S0.4 sets minimum effect sizes from the measured baseline.

---

## 6. Phases

### Phase S0 — Evaluation harness & baseline

**Goal**: Be able to say, with numbers, whether a change helped.

| Milestone | Work | Files |
|---|---|---|
| **S0.1** 🟡 | `evaluate_synthesis.py`: seeded test set, runs the pipeline, computes SECS (independent encoder), WER (Whisper), predicted MOS. Same pattern as `evaluate_preprocessing.py` (scratch data, never committed). | `backend/evaluate_synthesis.py` |
| **S0.2** 🟡 | Test corpus: ~20 adult speakers (LibriSpeech, as in the preprocessing study) **plus child and elderly speakers from sources whose licence permits evaluation use (verify each)**, plus an **expressive sentence set** — 40 sentences, each written in neutral/happy/sad/angry/question/exclamation variants, with the intended label. | scratch dir; sentence list committed as a small text fixture |
| **S0.3** 🟡 | Punctuation-contrast and emotion-classifier metrics (§4). | same tool |
| **S0.4** | Record baseline numbers in a new `SPEECH_QUALITY_STUDY.md` (decision-record style, like `PREPROCESSING_STUDY.md`). Confirm §4 targets. | doc |

**Tests**: unit tests for the metric functions on synthetic signals (pure sine rising/falling → F0 slope sign; identical embeddings → SECS 1.0); boundary: empty audio, 1-sample audio, silence. The harness itself is opt-in (needs weights + network for first model download), excluded from the default suite like the existing evaluation tool.

**Gate**: Baseline recorded for every §4 metric; run reproduces to within noise with a fixed seed.

---

### Phase S1 — Text front-end & punctuation-aware prosody (current model)

**Goal**: Squeeze what Tacotron 2 can give, and fix the places where the pipeline *throws information away*.

| Milestone | Work | Notes |
|---|---|---|
| **S1.1** 🟡 Normalisation | Replace/extend `english_cleaners`: currency, percentages, dates, times, ordinals, acronyms (`NASA` vs `FBI`), URLs, emails, units. Keep `inflect` for numbers. | Pure functions → very testable. Keep the output inside the existing symbol set so the checkpoint still works |
| **S1.2** 🟢 Punctuation-aware segmentation | Rewrite `text_chunking.py` to return `Segment(text, terminal, strength)` instead of bare strings; stop merging sentences with different terminals (`!`, `?`, `.`, `…`). | Merging is what flattens a `!` into the sentence before it |
| **S1.3** 🟡 Punctuation-aware pauses | Pause duration by boundary type: comma ≈ 0.12 s, semicolon/colon ≈ 0.25 s, full stop ≈ 0.4 s, `?`/`!` ≈ 0.45 s, paragraph ≈ 0.7 s, ellipsis ≈ 0.6 s. Insert **inside** a chunk too (comma → short silence in mel space) rather than only between chunks. Settings, not constants. | Replaces the single `TTS_CHUNK_PAUSE_SECONDS` |
| **S1.4** 🟡 Wider input charset | Accept `…`, `—`, `–`, curly quotes, `*emphasis*`, ALL-CAPS runs. Map to supported symbols **before** the symbol check, and record the mapping as prosody hints (emphasis → S5). | Today these are rejected with a 422 |
| **S1.5** Terminal-aware post-processing (fallback only) | For `?`: gentle pitch-rise on the last segment; for `!`: small gain/tempo lift — applied in the vocoder-output domain (e.g. WORLD/`pyworld` or phase-vocoder), **flagged experimental**. | Honest expectation: modest and sometimes artefacted. Keep only if the S0 punctuation-contrast metric improves *and* the listening test does not penalise it. Drop it once S4 ships |
| **S1.6** Cross-chunk continuity | Carry the last N mel frames (or the decoder state) as context into the next chunk; crossfade the join. Removes the pitch/energy "reset" at chunk edges. | Reference SV2TTS does not do this; requires care with the Tacotron decoder API |

**Tests** (CLAUDE.md §4.1):
- *Unit*: normaliser table tests (`$4.50`, `3rd`, `NASA`, `Dr.`, `10:30`, `5%`); segmenter tests per terminal type; pause table.
- *Integration*: `POST /synthesize` with mixed-punctuation text returns 200 and a duration that grows with pause settings.
- *Boundary*: only punctuation (`"?!"`), 500-char text with no spaces, empty after normalisation, ellipsis runs `.....`, Unicode quotes, text that previously produced a 422 and now passes.
- *Gateway*: `curl` the same sentence with `.`, `?`, `!` and compare durations/contours with the S0 tool.

**Gate**: WER does not regress; punctuation-contrast metric improves measurably; no new 5xx or truncation (`hit the 900-frame cap` warning rate unchanged or lower).

---

### Phase S2 — Voice-profile quality (embedding & enrollment)

**Goal**: A better, more stable representation of *who* is speaking.

| Milestone | Work |
|---|---|
| **S2.1** 🟡 Multi-clip profiles (aggregation done, S2.1a; storage and API open, S2.1b) | Let a profile be built from several clips (new `voice_profile_samples` table or JSON column); embedding = normalised mean of per-clip embeddings (utterance-level, as resemblyzer's own `embed_speaker` does). Alembic migration; soft delete and erasure must cover every stored sample file. |
| **S2.2** Quality scoring at upload | Per clip: SNR estimate, clipping ratio, voiced seconds, band-limit detection (telephone), reverb (DRR proxy). Return a `quality` object and actionable hints ("too noisy", "too short") instead of silently accepting poor audio. Reject only below a hard floor. |
| **S2.3** Reference enhancement (optional, flagged) | Speech enhancement/de-noise on the reference before embedding, **only** if S0 shows it raises SECS — `PREPROCESSING_STUDY.md` already shows preprocessing can lower similarity, so this must earn its place. |
| **S2.4** Embedding-level quality | Compare resemblyzer against a stronger/more suitable speaker representation (ECAPA-TDNN, or the new engine's own conditioning from S4); keep `embedding_version` on the profile so old profiles still work and new ones can be re-derived from the stored sample. |
| **S2.5** Best-of-N | Synthesize N candidates (N=2–4), score each against the profile embedding with the independent encoder (+ a WER check on short text), return the best. Cost scales with N — enabled by setting, off on CPU deployments unless the RTF budget allows. |

**Tests**: *unit* — quality scorer on synthetic noisy/clipped/telephone signals; embedding averaging is order-independent and L2-normalised. *integration* — multi-sample upload, per-clip failure leaves no partial profile (no residual files — CLAUDE.md §4.2), erasure removes all samples. *boundary* — 1 vs 20 clips, one bad clip among good ones, all-silence, duplicate clip.

**Gate**: SECS improves on the S0 set with multi-clip profiles; old profiles still synthesize unchanged; Alembic upgrade/downgrade round-trip verified (including on real Postgres per the existing recipe).

---

### Phase S3 — Vocoder & output polish

**Goal**: Remove the "telephone" ceiling and WaveRNN's cost.

| Milestone | Work |
|---|---|
| **S3.1** Neural vocoder swap | Replace WaveRNN with **HiFi-GAN** (already named in `project_description.md`). Fast (GPU and CPU far faster than WaveRNN), good quality. Train/fine-tune on the synthesizer's mel features (80-bin, 16 kHz params must match) — or use a universal vocoder trained on the target mel config. |
| **S3.2** Bandwidth (**priority**, child/high-pitch voices) | Moving to 22.05/24 kHz requires a synthesizer trained at that rate (so this milestone pairs with S4). Until then, an optional **bandwidth-extension** network (16 → 24/48 kHz) on the output is an interim, evaluated by the S0 MOS. |
| **S3.3** Loudness & cleanup | Normalise to a target LUFS (e.g. −18 LUFS, true-peak ≤ −1 dBTP) instead of raw clip-to-±1; de-click at chunk joins; DC-offset removal; short fade in/out. |
| **S3.4** Quality gate | Cheap automatic checks before returning: silence ratio, clipping, abnormal duration vs text length (catches Tacotron's "stuck loop"/early-stop). On failure, retry with a new seed (bounded), then return an error — never silently serve broken audio. |

**Tests**: *unit* — loudness function hits target ±0.5 LU on known signals; gate flags truncated/looped/silent signals; vocoder wrapper shape contracts using a mock (like `_MockVocoder`). *integration* — pipeline with the new vocoder behind its setting; fallback to WaveRNN when the HiFi-GAN checkpoint is absent (checksum manifest extended). *boundary* — 1-frame mel, 900-frame mel, NaN/Inf input.

**Gate**: MOS up, RTF down on CPU; checkpoint SHA256 added to `weights_manifest.json` and verified at load (same discipline as today).

---

### Phase S4 — Engine abstraction & expressive acoustic model

**Goal**: Replace the component that fundamentally cannot do emotion.

| Milestone | Work |
|---|---|
| **S4.1** `TTSEngine` interface | `prepare_voice(audio) -> VoiceConditioning`, `synthesize(text, conditioning, style) -> waveform`, `capabilities()` (emotions supported, max chars, sample rate). Wrap today's code as `Sv2ttsEngine`. Engine chosen by `TTS_ENGINE` setting; health/readiness report the active engine. No behaviour change — pure refactor with the whole existing suite passing. |
| **S4.2** Candidate shortlist & decision record | Evaluate in `SPEECH_QUALITY_STUDY.md` on the S0 set: English zero-shot cloning TTS with style/emotion conditioning, e.g. **StyleTTS 2**, **XTTS-v2**, **F5-TTS**, **OpenVoice v2**, **Fish-Speech/CosyVoice-class** models (multilingual ones only matter for their English quality). Compare SECS, WER, MOS, emotion accuracy, RTF on CPU and GPU, VRAM/RAM, **and licence of code and weights (commercial use, dataset terms)**. The list is a starting point from general knowledge, not a verified comparison — Phase S4.2 *is* the verification. |
| **S4.3** Integrate the winner | New engine class, weights provisioning via `download_weights.py` with checksums, `weights_manifest.json` entries, load-time verification, warm-up and readiness integration, same inference semaphore/timeout/queue rules (`_acquire_inference_slot`). |
| **S4.4** Deployment | Implement the two-tier design of §7.1: remote GPU inference worker behind `TTSEngine`, CPU engine as fallback, service-token auth, timeouts and cold-start handling. Railway has no GPU, so the worker lives on a separate provider. Fallback to `Sv2ttsEngine` on failure/timeouts. |
| **S4.5** Profile migration | Profiles store the SV2TTS embedding today. New engines condition on reference audio and/or their own embedding: store a `conditioning` blob + `engine` + `version` per profile and re-derive lazily from the retained sample (needs S2.1's stored samples). |

**Tests**: contract tests run against **both** engines with mocks (same interface test suite); integration tests with the engine mocked end to end; boundary: engine missing → 503 with clear message, fall back when configured; checksum mismatch refuses to load; old-engine profile still works.

**Gate**: Candidate beats baseline on SECS **and** MOS **and** is within the latency budget (§9) **and** has an acceptable licence — otherwise record "no-go" and stay on S1–S3 improvements.

---

### Phase S5 — Emotion & style control

**Goal**: The speech reacts to what the text says. This is the phase that delivers anger, sadness, joy and punctuation-driven delivery.

| Milestone | Work |
|---|---|
| **S5.1** Text analysis service | `backend/services/text_analysis.py`. Per sentence, produce `{emotion, intensity, arousal, valence, emphasis_words, pace}` from: (a) punctuation (`!` → raised arousal, `?` → rising intent, `…` → hesitant/sad, `!!!`/ALL-CAPS → high intensity), (b) lexical/semantic emotion classification with a small local model (e.g. a distilled emotion text classifier) — **local, no external API** (cost, privacy, determinism; CLAUDE.md §4.2). |
| **S5.2** Style mapping | Map the analysis to the engine's controls. For a reference-conditioned engine: choose/mix style reference vectors per emotion (a style bank extracted from licensed emotional corpora — ESD, RAVDESS, CREMA-D, EmoV-DB; **check each licence and speaker-consent terms**). For an engine with explicit emotion/prosody inputs: pass labels/F0/energy/duration targets. Style must change *delivery only*, not speaker identity — verify with SECS across emotions. |
| **S5.3** Per-sentence application | Segment (S1.2) → analyse → synthesize each with its own style → join with S1.3 pauses and S1.6 continuity. A text that moves from calm to angry should audibly shift mid-paragraph. |
| **S5.4** User override | Optional `emotion` (`auto` default, or `neutral|happy|sad|angry|…`) and `intensity` on the request; `auto` uses S5.1. Lightweight inline markup for power users (`[sad]…[/sad]`, `*stress*`) parsed in S1.4. |
| **S5.5** Emotion-vs-identity fine-tuning (only if needed) | If a stock engine's emotions are weak or leak speaker identity, fine-tune/adapt on emotional data with speaker-adversarial or disentanglement training. Heavy; do it only on evidence from S0 metrics. Training code and data stay out of the repo (like `weights/`). |

**Tests**: *unit* — analyser table tests (`"I can't believe you!!"` → angry/high; `"I miss her..."` → sad/low-arousal; `"Really?"` → question; neutral factual sentence → neutral), deterministic output; style mapping covers every label, unknown label → neutral. *integration* — request with each `emotion` value returns 200; invalid value → 422; `auto` vs explicit differ in the analysis payload (engine mocked). *boundary* — empty/very short/mixed-language sentences, emoji (stripped), contradictory cues (`"I'm so happy…"` sad punctuation), sarcasm (documented as a known limitation, not a bug).

**Gate**: Emotion accuracy ≥ target on the S0 expressive set; punctuation-contrast ≥ target; SECS drop across emotions ≤ 0.03 vs neutral; listening test win rate ≥ 70 %.

---

### Phase S6 — Long-form, non-verbal expression & speaker adaptation

**Goal**: Close the remaining gap to "human".

| Milestone | Work |
|---|---|
| **S6.1** Long-form | Raise the 500-char cap by streaming segment-by-segment generation with a persisted job (async task, progress, partial results) instead of a single request — also the right shape for any slower model. Keep per-request limits for abuse control. |
| **S6.2** Non-verbal tokens | Optional tags — `[laugh]`, `[sigh]`, `[breath]`, `[pause]` — if the chosen engine supports them natively; otherwise a curated, **licensed** library of generic (not speaker-cloned) non-verbal clips mixed at segment boundaries. Do not synthesise a real person's laugh without engine support and consent coverage. |
| **S6.3** Prosody refinement | Natural variation (micro-timing, F0 jitter within bounds) to avoid the "same every time" feel; speaking-rate follow-through from the reference speaker's measured rate. |
| **S6.4** Per-user adaptation (**in scope**, decided Q3) | With explicit consent and enough clean audio (minutes, not seconds): speaker adaptation (adapter/LoRA-style) as an opt-in "high-fidelity voice" run on the GPU worker (§7.1) via a queue, stored per profile and **deleted with the profile**. Largest quality jump for identity; also the largest cost, storage and misuse surface. Needs its own consent text version bump. |

**Tests**: job lifecycle (queued → running → done/failed/cancelled, no orphan files after cancel), resume after restart, tag parser round trip (valid/invalid/unbalanced tags), adaptation job isolation (user A's adapter never applied to user B's request), erasure removes adapters.

**Gate**: Long text (≥ 2 000 chars) stays stable (WER, no drift); adapted profile improves SECS on held-out text; deletion proven end to end.

---

### Phase S7 — API, frontend, safety, rollout

**Goal**: Ship it safely and make it usable.

| Milestone | Work |
|---|---|
| **S7.1** API contract | Additive, backwards-compatible fields (`emotion`, `intensity`, `quality` preset, `seed`); response adds `engine`, `emotion_used`, quality/duration metadata. Refresh `frontend/contract/openapi.json` (`python -m backend.export_openapi`; a test fails if stale). Generation rows record engine/version/emotion for audit. Alembic migration. |
| **S7.2** Safety | (a) Consent gate unchanged and enforced for every engine; (b) **inaudible watermark** in addition to WAV metadata (metadata is stripped by any re-encode); (c) rate limits per user scaled to the engine's cost; (d) abuse review for high-fidelity/adapted voices; (e) keep erasure complete (§6 critical rules: soft delete + file removal). |
| **S7.3** Observability | Prometheus metrics: per-engine RTF, queue time, gate-retry rate, fallback rate; log emotion distribution (labels only, never raw text). |
| **S7.4** Rollout | Feature flags (`TTS_ENGINE`, `EMOTION_CONTROL_ENABLED`), canary by user %, kill switch = config change back to `Sv2ttsEngine`. Re-run the S0 suite on staging before each flip. |
| **S7.5** Frontend (after the backend gate, CLAUDE.md §2) | Emotion selector + intensity slider with an `Auto` default, preview of detected emotion per sentence, enrollment guidance driven by the S2.2 quality hints, multi-sample upload, long-form progress, clear "AI-generated" labelling kept. Follows `FRONTEND_UX_IMPROVEMENT_PLAN.md` conventions and the visual-baseline/CI workflow. |

**Tests**: contract test fails on stale OpenAPI; old clients (no new fields) get identical behaviour; watermark detected after MP3 round-trip and resampling; fallback works with the new engine forcibly failing; full backend suite zero-warning (§3.3).

**Gate**: Backend suite green; staging S0 run meets targets; human listening test passed; rollout runbook added to `RUN_AND_VALIDATE.md`.

---

## 7. Risks & open decisions

| # | Risk / decision | Mitigation |
|---|---|---|
| R1 | **Licences** of the best open models/datasets may forbid commercial use | S4.2 licence check is a hard gate; keep S1–S3 gains independent of any new model |
| R2 | **Compute**: expressive models are slower; deployment is CPU-only | RTF budget (§9); GPU/inference-service decision at S4.4; best-of-N and adaptation are opt-in |
| R3 | **Misuse**: better cloning = better impersonation | Consent gate, watermark, rate limits, erasure, adaptation opt-in with a new consent version |
| R4 | **Emotion from text is ambiguous** (sarcasm, irony, mixed feelings) | `auto` is a default, never a lock; user override; document known limits instead of promising "perfect" |
| R5 | Emotion data/speaker consent for style banks | Use only licensed corpora; record provenance in the study doc; no scraping |
| R6 | Heavy new dependencies (Whisper, emotion models, new TTS) bloat the image and CI | Keep evaluation-only deps in `requirements-dev.txt`; runtime deps pinned via `requirements.lock.txt` (`relock_requirements.py`); check `backend/Dockerfile` size impact |
| R7 | Existing profiles/generations break on engine change | `engine` + `embedding_version` columns; lazy re-derivation; old engine kept as fallback |
| ~~Q1~~ | **Decided (2026-10-10)**: do not assume Railway CPU only. Use a **two-tier design**: a CPU tier that must work everywhere, and an optional GPU inference worker for the high-quality tier (see §7.1). S4.2 benchmarks decide the split | Owner confirms provider before S4.4 |
| ~~Q2~~ | **Decided**: English only. Drops multilingual models from the S4.2 shortlist; the normaliser (S1.1) stays English-specific | — |
| ~~Q3~~ | **Decided**: the target is faithful reproduction of **any** voice (male, female, child, elderly; any pitch, depth, brightness). Adds stratified evaluation (S0), pitch/formant fidelity checks (S2), 24 kHz output as a priority (S3) and promotes per-user adaptation (S6.4) to **in scope**; see §7.2 | — |

---

### 7.1 Hosting: GPU vs CPU (decision record)

GPU hosting exists and is cheap for low traffic. Providers change prices and products often, so
**verify current pricing and availability before choosing**; categories (from general knowledge, not
checked today):

| Option | Examples | Fit |
|---|---|---|
| Serverless GPU, per-second billing, scale to zero | Modal, RunPod Serverless, Baseten, Replicate, Hugging Face Inference Endpoints, Google Cloud Run with GPU | Best fit for bursty, low-volume traffic. Cost: cold start (model load) of seconds to tens of seconds |
| Rented GPU VM | Lambda, RunPod pods, Vast.ai, AWS/GCP/Azure | Predictable latency; pays while idle |

**Architecture (keeps the current stack)**: FastAPI + Postgres stay where they are. A separate
**inference worker** (same `TTSEngine` interface, S4.1) runs on the GPU host and is called over
HTTPS with a service token. The in-process CPU engine remains the **fallback** when the worker is
cold, failing or over budget. Audio stays on the app's storage; the worker is stateless and must not
persist user audio (privacy, erasure).

**Making the CPU tier better** (do these regardless, they also cut GPU cost):
- Non-autoregressive acoustic models (no word skipping, parallel decoding) and a fast vocoder (HiFi-GAN / Vocos-class) instead of WaveRNN.
- int8 / fp16 quantisation and ONNX or `torch.compile`; thread caps already handled by `cpu_limits.py`.
- Cache the speaker conditioning per profile (computed once at upload, never per request).
- Short-text fast path; stream segment by segment.

**Honest expectation**: strong zero-shot cloning *with* emotion control at high fidelity is still
easiest on a GPU. The CPU tier will likely be "clearly better than today" (S1–S3: better vocoder,
prosody, 24 kHz), and the GPU tier carries the full-expressiveness target. S4.2 benchmarks every
candidate on **both** this dev machine's CPU (24 cores) and its RTX 4060 so the split is decided by
data.

### 7.2 Voice coverage: every kind of speaker

"Perfect for every voice" is the hardest requirement here. Where the current system is weak, and
what the plan does about it:

| Voice type | Why it is hard | Plan |
|---|---|---|
| **Children** | Fundamental frequency ~250–400 Hz and higher formants; much energy above 8 kHz is lost at 16 kHz; almost no child speech in LibriSpeech/LibriTTS-style training data | 24 kHz+ output (S3.2 becomes priority); explicit F0/formant-fidelity metric; per-user adaptation (S6.4); data and legal limits below |
| **Elderly** | Creaky/breathy voice, tremor, irregular F0, slower rate | Evaluate on elderly speakers; S6.3 rate follow-through; adaptation |
| **Very low / very high pitch** (deep male, high female) | Zero-shot models regress toward the average voice | F0 range checks (S2.2), pitch-aware conditioning (engine choice criterion in S4.2) |
| **Breathy, nasal, accented, whispered** | Speaker encoders capture identity, not voice quality | Adaptation; report per-group SECS so gaps are visible, not averaged away |

New measurements (added to S0): evaluate **per group** (adult male, adult female, child, elderly,
plus low/high-pitch tails) and report, in addition to SECS: **median F0 error in semitones**,
**F0 range ratio**, **long-term spectral/formant distance** between reference and clone. A model
that passes on average but fails children does not pass.

**Constraints that cannot be engineered away**:
- A zero-shot clone from 10–30 s will not be perfect for every voice; **adaptation on more audio is the route to "indistinguishable"**, hence S6.4 is in scope.
- **Children's voices**: collecting, training on or cloning a child's voice raises consent (parent/guardian), privacy and legal duties (COPPA/GDPR-style rules). Add to the consent flow before enabling: confirm the speaker is an adult or that a guardian consents; keep the plan's erasure guarantees. Public child-speech datasets usually carry restrictive licences: **check each before any training use**.
- Quality of the *recording* caps quality of the clone (S2.2 guidance matters).

## 8. Effort & ordering (rough)

| Phase | Relative effort | Risk | Payoff |
|---|:---:|:---:|:---:|
| S0 | S | Low | Enables everything |
| S1 | M | Low | Medium (punctuation handling, fewer artefacts); **ceiling set by Tacotron** |
| S2 | M | Low–Med | Medium–High (identity) |
| S3 | M | Medium | High (clarity, speed) |
| S4 | L | High | **Highest** (unlocks expressiveness and fidelity) |
| S5 | L | Medium | **Highest** (delivers the emotion/punctuation goal) |
| S6 | L | Med–High | Medium–High, optional |
| S7 | M | Medium | Required to ship |

**Recommended first slice**: S0 → S1.1–S1.3 → S2.1–S2.2 → S4.1/S4.2 (decision record). That produces a
baseline, immediate gains, and the evidence needed to commit to the expensive part.

## 9. Budgets (set in S0, enforced from S3)

- **RTF** on the target host: stated per engine in `SPEECH_QUALITY_STUDY.md`; the engine may not ship if it breaks the existing `INFERENCE_CALL_TIMEOUT_SECONDS` at the maximum text length.
- **Memory**: weights + activations within the container limit with the encoder, synthesizer and vocoder resident (current weights ≈ 0.4 GB).
- **Event-loop lag**: re-run `python -m backend.measure_event_loop_lag` for every new engine (P2-M6 finding must keep holding).

## 10. Per-milestone checklist (CLAUDE.md §3)

- [ ] Branch `feat/S<n>.<m>-<name>`, clean tree, plan reviewed
- [ ] `black backend/` + `isort backend/`; type hints and one-line docstrings
- [ ] Unit + integration + boundary tests; `pytest` zero failures **and zero warnings**
- [ ] Verification gateway (`curl`) run and recorded
- [ ] No `.env`, `weights/`, `uploads/`, `outputs/`, `__pycache__` in the index
- [ ] Conventional commit: `feat(tts): [Milestone S1.2] <subject>` (no AI attribution, §0)
- [ ] This file updated (`[x]`, commit hash, status, date), committed separately
- [ ] PR into protected `main`; `check`, `perf`, `visual` green; merge; re-run suite on `main`
- [ ] `/graphify --update` after editing docs (§11)
