# Speech quality: baseline record

Records the S0.4 baseline of SPEECH_QUALITY_PLAN.md (section 4 metrics). Tools:
`backend/prepare_eval_corpus.py`, `backend/evaluate_synthesis.py`. Date: 2026-10-10.

## Decision

The baseline exists and is **reproducible**, but it is only a partial baseline. It measures what the
current model does with a single sentence for adult voices. It does **not** measure intelligibility,
naturalness, emotion, real-time factor, or any child or elderly voice, and it cannot tell whether the
Phase S1 changes (typed segments, pauses, text normalisation) helped. The section 4 targets are kept as
proposed; none can be tightened or relaxed from this data alone.

## What was measured

* **Corpus**: 20 speakers from LibriSpeech test-clean (CC BY 4.0), chosen at even spacing by speaker id.
  Per speaker: one reference clip of 10 to 30 s given to the cloner, and five held-out real clips of 3 to
  20 s. Groups are **measured median-F0 bands**, split at 165 Hz: `adult_low_f0` (10 speakers, 87 to 162 Hz,
  mostly men) and `adult_high_f0` (10 speakers, 170 to 213 Hz, mostly women). They are not gender labels
  (the dataset has none in the file used).
* **Per speaker**: one clone of "You are coming to the meeting." (speaker similarity, pitch, spectrum), then five
  sentence stems each spoken ending in `.`, `?` and `!` with the same seed (punctuation contrast). 16 syntheses
  per speaker, 320 in all, on CPU with the real weights.
* **Seeding**: every synthesis is seeded from its (speaker, sentence) unit alone, so runs are paired.

Reproduce (about 40 minutes on 16 CPU threads):

```bash
python -m backend.prepare_eval_corpus --parquet <test.clean/0000.parquet> --out <corpus> --speakers 20
python -m backend.evaluate_synthesis --data-dir <corpus> --groups <corpus>/groups.json --speakers 20 --stems 5
```

## Results

Mean over speakers, with a 95% bootstrap interval over speakers. n = 10 speakers per group.

| Metric | adult_low_f0 (n=10) | adult_high_f0 (n=10) | All (n=20) | Plan target |
|---|---|---|---|---|
| Speaker similarity (SECS, resemblyzer) | 0.786 [0.759, 0.808] | 0.734 [0.673, 0.783] | 0.760 [0.726, 0.789] | every group within 0.05 of the best |
| Median pitch error (semitones) | 2.37 [1.24, 3.76] | 4.39 [1.90, 7.71] | 3.38 [1.97, 5.11] | ≤ 1 |
| Pitch range ratio (1.0 ideal) | 0.73 [0.48, 1.00] | 0.62 [0.45, 0.80] | 0.68 [0.52, 0.84] | 0.8 to 1.2 |
| Long-term spectrum distance (dB) | 5.35 [4.44, 6.34] | 6.38 [5.75, 7.01] | 5.87 [5.23, 6.43] | to be set |
| `?` ends higher than `.` (share of pairs) | 0.42 [0.30, 0.53] | 0.62 [0.47, 0.79] | 0.52 [0.41, 0.63] | ≥ 0.80 |
| `!` has wider pitch range and more energy than `.` (share) | 0.22 [0.12, 0.32] | 0.23 [0.14, 0.31] | 0.22 [0.16, 0.29] | ≥ 0.80 |

Speaker similarity differs between the groups by 0.051, just over the plan's 0.05 gap limit, so the
fairness gate (`within_gap_limit`) is **not met** here; with n = 10 the intervals overlap, so this is a
warning rather than a finding.

## What the numbers say

* **Pitch is the clearest weakness.** The clone's median pitch is off by about 3.4 semitones overall and
  4.4 for higher voices, against a target of 1. The pitch range is compressed (0.68 of the real speaker's;
  target 0.8 to 1.2). This is consistent with the model drifting toward an average voice, the risk
  recorded in plan section 7.2, and it is worse for the higher-pitched group. These are adults only; the
  child and elderly groups are expected to be worse and are **not measured**.
* **Exclamations are not rendered as exclamations.** A `!` version has both a wider pitch range and more
  energy than its `.` version in about 22% of pairs (target 80%).
* **Questions are at roughly chance** (0.52; a coin flip would give about 0.5): the final pitch is no more
  likely to rise for `?` than for `.`. This is consistent with a model that has no question input.
  The metric itself has **not been validated on natural speech** (a known question rendered by a human),
  so treat this row as indicative until it has a positive control.

## Reproducibility (the S0 gate)

The study was run twice, on two different checkouts of the repository (the pipeline before Phase S1,
`d9070cf`, and after S1.1 to S1.4, `f4d8cbe`), with the same tool, corpus and seeds. All six metrics were
**identical for all 20 speakers**. Two conclusions:

1. A fixed-seed run reproduces exactly, which is the S0 gate.
2. These stimuli are single sentences, so the typed segments and pauses of S1.2 and S1.3 (which act
   *between* segments) never apply to them, and S1.1 (normalisation) changes nothing in plain-word
   sentences. **The study as it stands is blind to Phase S1.** Whether S1 helped is therefore still unmeasured.

## Limits

* **Same-encoder judge**: speaker similarity is scored by the encoder that conditions the model, so it
  flatters the model and is only a relative number. It is not comparable with the 0.85 in
  PREPROCESSING_STUDY.md, which used a different protocol (and different sentences).
* One seed per unit, one sentence per speaker for similarity and pitch: wide intervals (see above).
* Adults, read English speech, clean recordings. No children, no elderly, no noisy or telephone references.
* Pitch comes from a probabilistic YIN tracker on 16 kHz audio, which can mis-track breathy or creaky speech.

## Next measurements, in order

1. **Multi-sentence and number-heavy stimuli** (a paragraph mixing `.`, `?`, `!`, digits, times, acronyms),
   run on both checkouts, so Phase S1 can finally be compared. Use word error rate with it.
2. Whisper word error rate, a predicted-naturalness model, an emotion classifier, and an
   **independent** speaker encoder (plan S0.1 and S0.3, still open).
3. A positive control for the question metric (natural questions).
4. Child and elderly speech from a source whose licence and consent terms have been verified.
