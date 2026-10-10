# Speech quality: baseline record

Records the S0.4 baseline of SPEECH_QUALITY_PLAN.md (section 4 metrics). Tools:
`backend/prepare_eval_corpus.py`, `backend/evaluate_synthesis.py`. Date: 2026-10-10.

## Decision

The baseline exists and is **reproducible**, but it is only a partial baseline (the Phase S1 comparison
further down adds multi-sentence stimuli and word error rate). It measures what the
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

## Phase S1 before and after (multi-sentence stimuli, with Whisper)

Added 2026-10-11 (`backend/evaluate_synthesis.py` with `--skip-single`). The first study's stimuli were
single sentences and could not see Phase S1; these are multi-sentence, scored by Whisper `small.en`
(faster-whisper, CPU, int8, greedy). Setup: 10 speakers from the same corpus, **5 per group** (alternating,
so the groups are balanced), 4 paragraphs (3 to 4 sentences of plain words mixing `.` `?` `!` `,` `;`) and
4 typed texts (times, dates, currency, percentages, fractions, units, emails, acronyms) per speaker, the same
seeds and tool on both checkouts: the pipeline before S1 (`d9070cf`) and after S1.1 to S1.4 (`4bc6470`).
Mean over speakers, 95% bootstrap interval over speakers; the change is paired per speaker.

| Metric | Before S1 | After S1 | Change (paired) | Speakers better |
|---|---|---|---|---|
| Typed-text WER (intended words) | 0.384 [0.358, 0.411] | 0.095 [0.070, 0.122] | **-0.289** [-0.335, -0.245] | 10 of 10 |
| Paragraph WER | 0.116 [0.040, 0.240] | 0.070 [0.031, 0.116] | -0.047 [-0.132, +0.016] | not significant |
| Audible pauses per paragraph | 1.38 [0.85, 2.05] | 2.60 [2.33, 2.85] | **+1.23** [+0.53, +1.73] | 9 of 10 |
| Mean pause length (s) | 0.23 [0.21, 0.26] | 0.50 [0.47, 0.53] | **+0.27** [+0.24, +0.30] | 10 of 10 |
| Speaking time per word (s) | 0.271 [0.258, 0.286] | 0.340 [0.326, 0.357] | +0.069 [+0.054, +0.080] | 10 of 10 (slower) |

By group, paragraph WER fell from 0.048 to 0.041 for the low-pitch group and from 0.184 to 0.098 for the
high-pitch group (n = 5 each, so only suggestive); typed WER fell from 0.360 to 0.080 and from 0.408 to 0.109.

### What this shows

* **S1.1 (normalisation) works for intelligibility.** On text with numbers, times, symbols and acronyms the
  listener model recovers the intended words far more often (word error rate 0.38 to 0.10, every speaker
  better). Before, `10:30` was read as "ten:thirty", `%` and `&` were dropped, and `FBI` was read as a word.
* **S1.2 and S1.3 (typed segments and pauses) do what they were built to do.** A paragraph now has audible
  pauses at its sentence ends (2.6 against 1.4 per paragraph; each paragraph has 3 to 4 sentence ends) and
  they are about twice as long (0.50 s against 0.23 s). The old pipeline merged sentences and left 0.15 s
  gaps, which often fall under the 0.2 s detection threshold.
* **Pace moved toward natural reading.** 0.27 s per word is about 220 words per minute; 0.34 s per word is
  about 176. Read speech is usually put at roughly 150 to 180 words per minute (general knowledge, not
  measured here), so the new pace is the more natural of the two, but only a listening test can say so.
* **No intelligibility regression** on plain paragraphs (the plan's S1 gate): WER is lower, though the
  difference is not statistically significant with 10 speakers.

### What this does not show

* **It is not a listening test.** Fewer ASR errors and longer pauses are consistent with better speech, not
  proof. The pause lengths are the plan's proposals and are untuned; 0.50 s may be too long for some
  listeners. The plan's gate still requires a blind listening test.
* **The typed-text reference is defined by the new normaliser.** Both the reference and the transcript go
  through the same `clean_text`, so the comparison is of *intended* words as the normaliser defines them
  ("ten thirty pee em"); a different but valid reading would count as an error. This favours the new
  pipeline somewhat, though the old one failed on plain cases (dropped symbols, "ten:thirty").
* **Punctuation contrast is unchanged**: S1 does not touch single-sentence delivery, so the question-rise
  and exclamation-lift numbers of the first table stand, and remain far from their targets.
* n = 5 speakers per group, 4 paragraphs and 4 typed texts each, one seed; adults only; Whisper is a
  proxy for a listener, and it can recover words a person would find odd.

## Next measurements, in order

1. ~~Multi-sentence and number-heavy stimuli with word error rate~~ (done, section above).
2. A predicted-naturalness model, an emotion classifier, and an **independent** speaker encoder
   (plan S0.1 and S0.3, still open), and a first blind listening test of the S1 pause lengths.
3. A positive control for the question metric (natural questions).
4. Child and elderly speech from a source whose licence and consent terms have been verified.
