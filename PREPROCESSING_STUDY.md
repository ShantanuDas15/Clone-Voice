# Upload preprocessing: evidence and decision

Resolves HARDENING_PLAN.md Pass 1 §4.10 ("does `preprocess_audio` hurt embedding
quality compared with resemblyzer's own preprocessing?"). Tool:
`backend/evaluate_preprocessing.py`. Date: 2026-09-29.

## Decision

`preprocess_audio` no longer peak-normalises to full scale. It boosts quiet audio to the
encoder's training level (-30 dBFS RMS) and leaves louder audio alone, which is
resemblyzer's own `normalize_volume(..., increase_only=True)`. Trimming and every
validation rule are unchanged, and no voice-activity detection was added.

Effect: the cloned voice is closer to the real speaker (below), with no regression when
the reference recording is poor.

Profiles already stored keep their embeddings (made with the old level); nothing is
re-embedded. New uploads use the new level.

## What was measured

Data: 20 speakers x 8 utterances (160 clips, 26 min) of read English speech from
LibriSpeech test-clean, taken from the Hugging Face dataset `openslr/librispeech_asr`
(license CC BY 4.0). It lives in scratch space and is never committed. No real speech
recorded by a user exists in the repository, so the study could not use any.

Pipelines compared (all feed the same encoder, `resemblyzer.VoiceEncoder`):

| Name | What it does |
|---|---|
| `current` | librosa trim, then peak-normalise to full scale (what uploads did) |
| `resemblyzer` | resemblyzer's `preprocess_wav`: -30 dBFS increase-only, VAD pause trimming, no librosa trim |
| `trim+level(inc)` | librosa trim, then -30 dBFS increase-only. **Adopted.** |
| `level-only`, `vad-only` | the two halves of `resemblyzer`, to find which one matters |
| `trim+level`, `trim+level+vad`, `current+vad` | other combinations (level in both directions, VAD) |

Three questions:

1. Do embeddings still separate speakers? (equal error rate over 12,720 pairs, bootstrap over speakers)
2. **Is the cloned voice closer to the real speaker?** The reference clip is embedded by the
   pipeline, the real TTS clones a sentence from it, and the clone is scored by cosine
   similarity against that speaker's *other* utterances (judge: resemblyzer's own
   pipeline). 20 speakers x 2 sentences = 40 paired units per pipeline. Synthesis is
   seeded per unit, so every pipeline gets the same random draws (the TTS is stochastic:
   the same pipeline scored 0.8145 and 0.8179 on two unseeded runs, which swamped the
   effect at first; with seeding a re-run reproduced its numbers exactly).
3. Is that still true when the reference recording is poor? (quiet, clipped, noisy,
   telephone-band; 12 speakers x 4 cases)

## Results

### Cloned voice vs the real speaker (clean references, 40 paired units)

| Pipeline | Mean similarity | vs `current` | 95% CI | Units improved |
|---|---|---|---|---|
| `current` | 0.8304 | baseline | | |
| `resemblyzer` | 0.8491 | +0.0187 | [+0.008, +0.030] | 75% |
| `vad-only` | 0.8489 | +0.0185 | [+0.008, +0.029] | 78% |
| `level-only` | 0.8479 | +0.0175 | [+0.007, +0.028] | 68% |
| **`trim+level(inc)`** | 0.8499 | **+0.0195** | **[+0.011, +0.028]** | **82%** |
| `trim+level` (level in both directions) | 0.8184 | -0.0120 | [-0.028, +0.004] | 42% |
| `trim+level+vad` | 0.8166 | -0.0138 | [-0.030, +0.002] | 32% |

Every variant that stops peak-normalising and never turns loud audio down gains about
0.018 to 0.020; VAD and trimming are not what matters. Turning loud audio *down* to
-30 dBFS loses the gain.

### Poor reference recordings (12 speakers, clone similarity vs `current`)

| Reference | `trim+level(inc)` - `current` | 95% CI |
|---|---|---|
| quiet (x0.03) | -0.0001 | [-0.026, +0.025] |
| loud, clipped (x8) | 0.0000 (identical input) | |
| noise (15 dB SNR) | +0.0105 | [-0.012, +0.033] |
| telephone band | +0.0202 | [-0.002, +0.042] |
| all 48 units | +0.0076 | [-0.003, +0.018] |

Never worse in any case.

### Speaker discrimination (160 clips, 20 speakers)

| Pipeline | EER % (95% CI) | d-prime | Cosine to `resemblyzer` |
|---|---|---|---|
| `current` | 0.71 (0.00 to 1.43) | 5.63 | 0.958 |
| `resemblyzer` | 0.18 (0.00 to 0.42) | 6.08 | 1.000 |
| `trim+level(inc)` | 0.36 (0.00 to 0.71) | 5.90 | 0.994 |

Read speech is easy: every pipeline is under 1% EER and the intervals overlap, so this
data cannot rank them. The adopted pipeline is not worse, and its embeddings are almost
identical to resemblyzer's own.

### Invariance to degradation (not the deciding measure)

Mean cosine between a clip's embedding and its degraded copy's: `current` 0.861,
`trim+level(inc)` 0.844. `current` scores higher mainly because peak normalisation
undoes gain changes (quiet 1.000 vs 0.955, clipped 0.824 vs 0.763). That measures how
*unchanged* the embedding is, not how good the clone is, and the direct measure above
shows no loss. Cost: about 130 ms per clip for every pipeline; no difference.

## How the decision was reached, and one correction

Before running, I fixed a rule: adopt an alternative only if it improved equal error rate
or invariance robustness, did not lower clone similarity, and cost no more than 50 ms per
clip. Two things turned out wrong with that rule, and I changed it rather than let it
decide by its letter:

- Invariance is not quality. `resemblyzer` and the adopted pipeline "lose" on
  invariance yet clone better. Before running the poor-reference experiment I
  replaced the invariance criterion with clone quality under degraded references,
  which is what a user actually experiences. By the original wording the adopted
  pipeline would not qualify (invariance -0.017, EER gain not significant).
- The 0.005 tolerance was smaller than the TTS's own run-to-run noise (about 0.004), so it
  could not decide anything until synthesis was seeded.

Two bugs in the tool itself were found and fixed on the way (a bootstrap that scored
duplicated speakers as false accepts, and a "level" variant that was a no-op because
resemblyzer's normaliser never turns loud audio down); both have regression tests.

## Limits

- Clean, read, English speech from 20 speakers. Real uploads (phone microphones, rooms,
  other languages) may behave differently.
- One encoder and one judge (resemblyzer's). The judge shares the encoder with the
  system being measured, so this is a similarity proxy, not a listening test. A human
  A/B on real recordings (the P2-M3 listening pass) is still the final check.
- 40 paired units on clean speech and 12 speakers on degraded references: the clean-speech
  gain is significant; the poor-recording results are "no worse", not "better".

## Reproduce

```bash
# data: one directory per speaker, at least 3 files each (16 kHz audio)
python -m backend.evaluate_preprocessing --data-dir <speakers/>                  # EER + invariance
python -m backend.evaluate_preprocessing --data-dir <speakers/> --clone 20 --clone-texts 2 --clone-only \
    --clone-pipelines "current,resemblyzer,trim+level(inc)"                      # clone quality
python -m backend.evaluate_preprocessing --data-dir <speakers/> --clone-degraded 12 --clone-only
```

The last two need the model weights and take 15 to 25 minutes on CPU.
