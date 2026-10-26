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
  so treat this row as indicative until it has a positive control (since run, S0.3b below: it separates real yes/no questions from statements with an AUC of 0.67).

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

## Multi-clip enrolment (S2.1a, 2026-10-11)

Does a profile built from several clips clone better than one built from a single clip? 20 speakers
(10 per group), reference clip alone against the unit-length mean of the reference plus two more of the
speaker's own clips (`aggregate_embeddings`). Both profiles are scored on the **same three held-out real
clips, never used for enrolment**, and every sentence (3 per speaker) is synthesized with both profiles
and the same seed, so the comparison is paired. Mean over speakers, 95% bootstrap interval over speakers.
Tool: `python -m backend.evaluate_synthesis ... --enroll-compare 3 --stems 3`.

| Metric | One clip | Three clips | Change (paired) | Speakers better |
|---|---|---|---|---|
| Embedding vs real speech (no synthesis) | 0.908 [0.874, 0.935] | 0.960 [0.948, 0.969] | **+0.052** [+0.031, +0.080] | 20 of 20 |
| Clone vs real speech (speaker similarity) | 0.761 [0.732, 0.787] | 0.786 [0.773, 0.801] | **+0.025** [+0.008, +0.046] | 14 of 20 |
| ... low-pitch group | 0.784 | 0.803 | +0.019 [+0.004, +0.033] | 7 of 10 |
| ... high-pitch group | 0.738 | 0.770 | +0.032 [-0.001, +0.067] | 7 of 10 |
| Median pitch error (semitones) | 2.68 [1.82, 3.59] | 2.44 [1.74, 3.22] | -0.24 [-1.01, +0.34] | 10 of 20 |
| Long-term spectrum distance (dB) | 5.03 [4.53, 5.62] | 4.79 [4.53, 5.06] | -0.25 [-0.81, +0.25] | 10 of 20 |

### What this shows

* **The speaker embedding itself gets clearly better** with more clips: closer to the speaker's real speech
  for all 20 speakers, and most for the higher-pitched group (+0.074), whose single-clip embeddings were
  the noisiest.
* **The clone gets modestly closer** (+0.025, interval above zero), and the gap between the pitch groups
  narrows from 0.046 to 0.033 (the plan's fairness limit is 0.05). The gain is smaller than the embedding's
  because the synthesizer is the other half of the chain.
* **The pitch error does not move** (-0.24 semitones, interval spans zero), and neither does the spectrum
  distance. **The 2.4 to 3.4 semitone pitch error found in the baseline is therefore not mainly caused by
  a noisy single-clip embedding**: aggregating clips will not fix it. It points at the model itself
  (regression toward an average voice) and so at the acoustic model and vocoder (S3, S4) and at
  per-user adaptation (S6.4), not at enrolment.

### Limits

* The judge is the same encoder that conditions the model, so the similarity gain is flattered (it is the
  same encoder that made the profile better). An independent encoder is still open (plan S0.1).
* n = 20 speakers, adults, one seed per sentence, three sentences; the pitch result is "no detectable
  change", not "no change".
* Three clips from the same recording session: clips recorded on different devices or in different rooms
  are untested.

### Same-speaker check for multi-clip uploads

With several clips, one may belong to a different person (a mistake, or a deliberate attempt to build a
voice from a mix). `clip_agreement` scores each clip against the mean of the others. On this corpus
(60 true-speaker clips from 20 speakers; 380 trials of one other person's clip among two true clips):

| Threshold | True clips wrongly flagged | Other-speaker clips caught |
|---|---|---|
| 0.65 | 0.0% | 73.2% |
| 0.70 | 1.7% | 87.1% |
| **0.75** | **1.7%** | **95.8%** |
| 0.80 | 3.3% | 99.5% |

0.75 is a reasonable **warning** threshold, but the encoder is a verification model of limited accuracy and
60 true clips is a small sample: flag for review, do not treat it as proof. It must not be the only consent
control (the consent gate stays). With fewer than three clips nothing can be flagged.

## Recording quality and the upload report (S2.2a, 2026-10-11)

Which defects in a *reference recording* actually hurt the clone? 10 balanced speakers, each cloned from a
clean copy and from seven degraded copies of the same reference clip (the clone is always scored against
the speaker's real, undegraded held-out speech; paired seeds). Tool:
`python -m backend.evaluate_synthesis ... --degrade-compare --stems 2`. Mean over speakers, 95% bootstrap
interval over speakers.

| Reference recording | Clone similarity | Change vs clean (paired) | Speakers worse |
|---|---|---|---|
| Clean | 0.772 | | |
| Noise, 20 dB SNR | 0.707 | **-0.064** [-0.079, -0.049] | 10 of 10 |
| Noise, 10 dB SNR | 0.671 | **-0.100** [-0.129, -0.070] | 10 of 10 |
| Noise, 5 dB SNR | 0.642 | **-0.129** [-0.165, -0.086] | 9 of 10 |
| Telephone band (4 kHz) | 0.734 | -0.038 [-0.064, -0.013] | 7 of 10 |
| Clipped (gain x3, about 0.3% of samples) | 0.733 | -0.038 [-0.058, -0.016] | 8 of 10 |
| Clipped (gain x8, about 6% of samples) | 0.647 | **-0.124** [-0.154, -0.098] | 10 of 10 |
| Very quiet (x0.03, about -52 dBFS) | 0.771 | -0.001 [-0.012, +0.010] | 5 of 10 |

**Noise and clipping do real damage, and even moderate noise hurts every speaker.** A quiet recording does
not, because the upload path already raises it to the encoder's level (this agrees with
PREPROCESSING_STUDY.md), so the scorer deliberately gives **no volume hint**. These are simulated defects
(white noise, an 8 kHz resample, digital gain): real rooms, codecs and microphones differ.

### Measures and thresholds

`services/audio_quality.py` measures four things on the whole decoded recording and turns them into hints.
Thresholds come from this study, checked on all 120 real clips and their degraded copies:

| Hint | Rule | Clean clips flagged | Defective clips caught |
|---|---|---|---|
| `noisy` / `very_noisy` | estimated SNR below 25 dB / 15 dB | 5.8% (of 120) | 98% of 20 dB-noise clips; 100% at 10 dB and below |
| `distorted` / `very_distorted` | flat full-scale runs above 0.1% / 2% of samples | 0.8% | 100% of x8; 52% of x3 |
| `band_limited` | energy above 4 kHz more than 45 dB below the band under it, or an original recorded at 8 kHz or less | 0.0% (clean never below -33.5 dB) | 100% (simulated phone band at -83 dB or lower) |
| `short` | under 10 s of speech | n/a | advice from the product's 10 to 30 s guidance, **not a measured effect** |

On the 20 reference clips through the real `assess_file`: 19 of 20 clean clips rated good (the one flagged
`noisy` is a genuinely noisy recording, about 24 dB); noise at 20 dB rated fair for 20 of 20; at 10 dB and
5 dB poor for 20 of 20; telephone band flagged for 19 of 20; x8 clipping flagged for 20 of 20 (16 poor);
x3 clipping for 10 of 20; very quiet audio raised no hint.

### Limits

* Simulated defects on read English speech from adults. Real phone audio, MP3 artefacts, room echo and
  other noise types (music, speech babble) are untested; **reverb is not measured at all** (the plan
  lists it; there is no tested measure yet).
* The SNR is a frame-energy estimate that assumes the clip has both speech and pauses; a recording
  with no pauses reads as noisier than it is.
* n = 10 speakers for the harm study; thresholds are tuned on the same corpus they are checked on.
  Treat them as a calibrated first version, to be re-checked on real uploads.
* The report is advice. It never rejects an upload: no measured level is bad enough to justify refusing
  someone their own voice, and the existing duration and silence floors still apply.

## Output quality gate (S3.4, 2026-10-11)

Question: can cheap checks on the vocoder output catch audio that should not be served, without
refusing ordinary speech? Corpus: 6 LibriSpeech test-clean speakers (3 low-F0, 3 high-F0, as in S0.2),
each cloned from one 10 to 30 s reference, real weights, CPU.

### Calibration (seed 0, 168 syntheses)

20 ordinary texts per speaker (1 to 25 words, questions, exclamations, numbers, abbreviations,
multi-sentence) and 8 stress texts (40 repeated words, a 60-letter word, a very long word, punctuation
only, repeated "the", digits, laughter, a single letter).

| Measure (120 ordinary outputs) | Range seen | Gate threshold |
|---|---|---|
| Decodes that hit the 900-frame cap | 1 of 120 outputs (a plain 22-word sentence, one speaker) | any |
| Loud level (95th percentile 20 ms frame) | -37 to -0.1 dBFS | below -45 dBFS is silent |
| Silent frames (30 dB under the loud level) | 0.4% to 67% | above 85% |
| Longest silent stretch | 0.02 to 0.90 s (the paragraph pause is 0.70 s) | above the longest configured pause + 1.0 s |
| Samples at full scale | up to 0.96%, except one 1-word output at 8.3% | above 2% |
| Duration / (0.29 s + 0.287 s x spoken words) | 0.68 to 1.64 (for 4 or more words) | outside 0.35 to 2.5 |

Spoken words are counted after text normalisation, so "10:30 a.m." counts as the words said.
Seconds per word alone is not usable: one-word texts ran 0.84 to 0.94 s per word while sentences ran 0.21
to 0.35, hence the length model and its exemption for texts under 4 words. A long single word is slow
but not broken (60 letters: 3.0 s, 5 times the model), which is why short texts are exempt.

The stress texts raised no further failure signal. Two of the 48 hit the frame cap (the 40 repeated
words, for two speakers).

### Held-out check (seed 1, 120 ordinary syntheses through the full pipeline, gate on)

| Outcome | Count |
|---|---|
| Passed first attempt | 118 |
| Failed, retried, then passed | 1 (clipping on "Why?", recovered) |
| Refused after both attempts | 1 (the 22-word "committee" sentence, truncated both times) |

### What this shows

* Truncation, the one failure seen on ordinary text, is detected exactly, because the synthesizer
  reports it; no audio heuristic is involved.
* The other checks did not fire on 118 of 120 ordinary outputs, apart from the one clipping case,
  which the retry fixed.

### Limits

* **Retrying with a new seed does not always fix truncation.** The refused sentence is 143 characters
  (under the 150-character chunk limit) and hit the cap for this speaker on both attempts, and for a
  different speaker in the calibration run. For a slow voice a chunk can need more than 900 frames.
  That is 1 of 120 ordinary requests refused (0.8%) with a clear error; a smaller chunk size on retry
  would probably recover it and is the first follow-up.
* Thresholds were set and checked on the same speakers (different seeds). Six speakers, adults only.
* **No known-bad audio other than truncation and the one clipped output was observed**, so the silence,
  long-gap and duration checks are guards with wide margins, not tested detectors of real failures.
  Babbling and word repetition by Tacotron are not detected at all.
* The checks use the raw vocoder output; the S3.3 levelling and edge fades come after.
* Every retry is a full synthesis, so a refused request costs about twice a normal one.

### Retry in smaller chunks (S3.4b)

Follow-up to the limit above. After a truncated decode the retry now splits the text into chunks half
as long (150, then 75, 37, floor 20 characters) instead of repeating the same decode. Checked on the
two texts that truncated, 6 speakers x 3 seeds each (36 full-pipeline runs, gate on, 2 attempts):

| Text | Served first try | Served after the smaller-chunk retry | Refused |
|---|---|---|---|
| 22-word "committee" sentence | 15 | 3 | 0 |
| 40 repeated words | 10 | 8 | 0 |

Every request that needed a retry (11 of 36) recovered; none was refused. Not paired with the old behaviour
on the same seeds, so this shows the new retry recovers these cases, not by how much it beats the old one.
The first attempt still truncates for these texts about a third of the time, so those requests cost two
syntheses of time.

## Engine candidates (S4.2a, 2026-10-11)

Question: is there an open engine that clones better than SV2TTS, takes emotion, can be used
commercially, and fits the hardware? The machine-readable record is `backend/eval_data/engine_candidates.json`
(a test keeps it complete and refuses a selectable engine whose licence is not recorded as ok).

### Licence and capability check (11 candidates)

Read from each project's own GitHub page, model card or LICENSE file. Page text was summarised, so before
any candidate is adopted its LICENSE file must be read in full.

| Candidate | Licence (code / weights) | Verdict |
|---|---|---|
| **Chatterbox** (Resemble AI) | MIT / MIT (LICENSE file read; model metadata) | **Candidate**, benchmarked below |
| Zonos v0.1 | Apache-2.0 / Apache-2.0 (metadata) | Licence ok; not benchmarked (needs `espeak-ng`, not installable here) |
| Fun-CosyVoice 3.0 | Apache-2.0 / Apache-2.0 (metadata) | Licence ok; not benchmarked (needs `sox`; instruct mode uses a separate checkpoint) |
| OpenVoice V2 | MIT / MIT | Licence ok; not benchmarked (tone converter on a separate base TTS) |
| OmniVoice | Apache-2.0 / not stated | Unclear weights licence; no emotion control described |
| StyleTTS 2 | MIT / terms attached | Rejected: no user emotion control; GPL phonemizer dependency; must disclose synthesis |
| F5-TTS | MIT / **CC-BY-NC-4.0** | Rejected: non-commercial weights |
| XTTS-v2 | MPL-2.0 / **Coqui Public Model License** | Rejected: non-commercial, company gone (CPML text not read) |
| Fish Audio S2 Pro | **Research licence** / same | Rejected: commercial use needs a separate written agreement (LICENSE file read) |
| IndexTTS2 / 2.5 | bilibili Model Use License / same | Rejected for now: commercial use needs contacting the authors (licence text not fetched); has the best emotion control found |
| Orpheus 3B | Apache-2.0 / not stated | Rejected: not trained for zero-shot cloning |

Chatterbox is the only strong candidate that is both commercially licensed and runnable here. Its
training data is described only as "0.5M hours of cleaned data", with no dataset names, so the terms of the
data behind the MIT weights cannot be checked. Every output carries the PerTh watermark and the README
gives no way to remove it (which S7.2 wants anyway). Its watermark package imports `pkg_resources`, which
current setuptools no longer ships, so a fresh install fails at model load until `setuptools<81` is pinned.

### Benchmark: Chatterbox against the production SV2TTS pipeline

Same 6 LibriSpeech test-clean speakers as the S3.4 calibration (3 low-F0, 3 high-F0), each cloned from one
10 to 30 s reference; the same 10 texts for both engines (1 to 25 words: statements, questions, an
exclamation, an ellipsis, numbers, a multi-sentence passage), one seed each; 60 outputs per engine. SV2TTS
ran through the full production pipeline (gate, levelling). Chatterbox is the original English 0.5B model at its
default settings (`exaggeration` 0.5, `cfg_weight` 0.5), speaker conditioning prepared once per speaker.
Scored with the S0 code: speaker similarity against the mean embedding of the speaker's real held-out
clips; pitch against the same clips; Whisper `small.en` word error rate against the normalised text (the
"Dr. ... 10:30 a.m." text is left out of WER because it has no single spoken form).

| Metric | SV2TTS | Chatterbox |
|---|---|---|
| Speaker similarity (mean, 95% CI) | 0.763 [0.741, 0.784] | **0.869** [0.855, 0.883] |
| Paired difference | | **+0.106** [+0.087, +0.125]; better for 56 of 60 outputs |
| Low-F0 / high-F0 group | 0.799 / 0.727 (gap 0.072) | 0.859 / 0.879 (gap 0.020, reversed) |
| Word error rate | 0.178 [0.096, 0.268] | **0.017** [0.003, 0.039] |
| Outputs with WER above 0.30 | 12 of 54 | 1 of 54 |
| Mean pitch error (semitones; target 1) | 4.4 | 2.0 |
| Pitch range, clone / real (target 0.8 to 1.2) | 0.80 | 1.33 (too wide) |
| Output sample rate | 16 kHz | **24 kHz** |

Speed and memory (this machine: RTX 4060 Laptop 8 GB, 24 CPU cores, 14 GB RAM):

| | SV2TTS | Chatterbox |
|---|---|---|
| GPU real-time factor (60 outputs) | 0.83 | **0.56** |
| GPU peak memory | 0.42 GiB | 3.6 GiB |
| CPU real-time factor (1 speaker, 7 texts) | 2.3 | **6.5** |
| CPU peak memory (resident) | 1.6 GiB | 6.7 GiB |
| Model load | 1.0 s (GPU), 2.6 s (CPU) | 7.3 s |

A real-time factor above 1 means slower than real time.

### Emotion control: the `exaggeration` setting

2 speakers x 4 sentences (emotional, sad, a question, a neutral statement) at exaggeration 0.25, 0.5, 1.0 and 1.5:

| Exaggeration | Level (dBFS) | Pitch range (semitones) | Similarity to the real speaker | Similarity to the 0.5 version |
|---|---|---|---|---|
| 0.25 | -28.6 | 14.6 | 0.873 | 0.902 |
| 0.5 | -26.6 | 16.9 | 0.877 | 1.000 |
| 1.0 | -22.8 | 15.2 | 0.856 | 0.878 |
| 1.5 | -18.3 | 15.9 | 0.810 | 0.810 |

Duration is nearly constant. The setting mostly moves loudness (about 10 dB across the range); pitch range
does not rise with it. At 1.5 the speaker similarity falls 0.067 from the default, more than the plan's
0.03 limit for an emotion change; at 1.0 it falls 0.021, inside it.

### What this shows

* On this sample Chatterbox is a large step up for voice similarity, intelligibility and pitch error, treats
  both pitch groups alike, outputs 24 kHz (removing the 8 kHz ceiling), and is faster than SV2TTS on a GPU.
  The similarity is judged by resemblyzer, the encoder that conditions SV2TTS, so the comparison favours
  SV2TTS if anything.
* The original model cannot replace SV2TTS on a CPU-only host (but see the variants below): 6.5 times slower than real time and 6.7 GiB of memory.
  A 7 s sentence would take about 45 s, over the 30 s per-stage timeout. The two-tier design in section 7.1
  stands: Chatterbox as a GPU tier, SV2TTS as the CPU fallback.
* `exaggeration` is one intensity knob that behaves mostly like loudness. It is not the happy, sad and angry
  control that S5 needs. Reaching those needs an engine with labelled emotions, or reference-style
  conditioning (S5.2), or the paralinguistic tags of the smaller Chatterbox variants (S6.2).

### Limits

* Six adult speakers, ten texts, one seed. No child or elderly speech.
* **No predicted naturalness (MOS), no emotion classifier and no listening test**, so the plan's gate
  ("beats the baseline on similarity and MOS") is half evidenced. Pitch range overshoots (1.33 against a
  0.8 to 1.2 target), which a listener might hear as exaggerated.
* The CPU figures are one speaker and seven texts. Chatterbox-Turbo (350M) and Chatterbox-Nano (110M) were
  not run in S4.2a. **Correction (S4.2b):** this section first said the installed package did not include
  them. That was wrong: I had not checked. Turbo was in the package; only Nano needed a newer version. Both
  are measured in the next section.
* Zonos, CosyVoice 3 and OpenVoice V2 are licence-clean but unbenchmarked; Zonos is the strongest of them
  on paper (emotion controls, 44 kHz) and needs `espeak-ng`.
* The generation scripts are scratch code and are not committed. The scoring is now the committed, tested `backend/score_engine_outputs.py` (S4.2b), which reproduces these numbers exactly.
* Training-data provenance for Chatterbox is undisclosed. Whether that is acceptable is a decision for the
  owner (plan risk R1), not a test result.
* Hosting (plan Q1) is still open: Chatterbox needs a GPU host with about 4 GiB of free memory.

## Chatterbox variants: Turbo and Nano (S4.2b, 2026-10-11)

Question: can a smaller Chatterbox keep the quality gain and run on a CPU? Same speakers, texts, scorer and
baseline as the section above, now run by the committed `backend/score_engine_outputs.py` (it reproduced the
S4.2a figures to the third decimal). Turbo (350M) comes with the PyPI package; Nano (110M) needs the GitHub
master branch (`from_pretrained(device, nano=True)`). Both are English and MIT-licensed per their model cards.

### Quality (60 outputs each, GPU)

| Metric | SV2TTS | Chatterbox 0.5B | Turbo 350M | Nano 110M |
|---|---|---|---|---|
| Speaker similarity | 0.763 | 0.869 | 0.856 [0.840, 0.870] | 0.856 [0.838, 0.873] |
| Paired gain over SV2TTS | | +0.106 (56 of 60) | **+0.092** [+0.072, +0.113] (52 of 60) | **+0.093** [+0.074, +0.113] (53 of 60) |
| Word error rate | 0.178 | 0.017 | **0.003** | **0.005** |
| Outputs with WER above 0.30 | 12 | 1 | 0 | 0 |
| Mean pitch error (semitones) | 4.4 | 2.0 | 2.1 | 3.4 [2.1, 5.2] |
| Pitch range, clone / real (target 0.8 to 1.2) | 0.80 | 1.33 | 1.15 | 1.11 |
| Low-F0 / high-F0 gap | 0.072 | 0.020 | 0.031 | 0.022 |

Against the original, Turbo and Nano are 0.014 and 0.013 lower in similarity (intervals [-0.021, -0.007] and
[-0.023, -0.004]): small but real. Both keep nearly all of the gain, have the lowest word error, and bring the
pitch range inside the target. Nano's pitch error is the weakest of the three and its interval is wide.

### Speed and memory

| | SV2TTS | Chatterbox 0.5B | Turbo | Nano |
|---|---|---|---|---|
| GPU real-time factor | 0.83 | 0.56 | **0.25** | **0.12** |
| GPU peak memory | 0.42 GiB | 3.6 GiB | 3.2 GiB | 2.3 GiB |
| CPU, 24 threads (machine default) | 2.33 | 6.48 | 2.13 | 1.28 |
| CPU, 8 threads | 1.88 | not run | 2.08 | **0.76** |
| CPU, 4 threads | not run | not run | not run | 1.12 |
| CPU memory (resident) | 1.6 GiB | 6.7 GiB | 5.7 GiB | 4.3 GiB |

CPU runs are one speaker and seven texts (a real-time factor below 1 is faster than real time). The thread
count matters more than the machine: with all 24 threads Nano is slower than with 8, so a deployment must cap
threads (`TORCH_NUM_THREADS`, `cpu_limits.py`) to the cores it really has. Nano's own claim, "3x faster than
real time on 8 cores" (a factor of 0.33), was **not** reproduced: 0.76 here. The first-time GPU loads took 513 s
(Turbo) and 122 s (Nano) because they include downloading; cached CPU loads took 4 to 6 s.

### Paralinguistic tags

Turbo and Nano take `[laugh]`, `[chuckle]` and `[cough]` in the text, and ignore `exaggeration`. Three
sentences with and without a tag, 2 speakers: with the tag the clip was longer in 6 of 6 cases (about +1.0 s)
and had a louder burst (+2.8 dB Turbo, +4.8 dB Nano). That shows the tag changes the audio in the expected way;
it does not show it sounds like a laugh, which needs a listener.

### What this shows

* **Nano is the first engine here that is both better than SV2TTS and faster than real time on a CPU**: similarity
  +0.093, almost no word errors, 24 kHz, real-time factor 0.76 on 8 threads. The cost is memory: 4.3 GiB against
  1.6 GiB. That revises the S4.2a conclusion ("CPU not viable") for this variant.
* Turbo is the sensible GPU variant: half the original's time and memory for 0.014 of similarity, plus tags.
  The original keeps the only intensity control (`exaggeration`).
* **None of them gives happy, sad or angry.** Tags are sound events; `exaggeration` is an intensity that mostly moves
  loudness. S5's labelled emotion still needs another engine (Zonos is unbenchmarked; IndexTTS2 is not licensable
  without an agreement) or reference-style conditioning.

### Limits

* Six adult speakers, ten texts, one seed; the CPU result is one speaker and seven texts; no children or elderly.
* **Still no predicted naturalness, emotion classifier or listening test.** The plan's gate needs them.
* Nano's memory (4.3 GiB) may not fit the production container; the container limit was not checked.
* Nano needs a GitHub-master install, not the PyPI release; pinning a commit and its dependency set is S4.3's work.
  Training data of all three is undisclosed, the watermark is always on, and its package needs `setuptools<81`.
* The tag check measures duration and level, not content.

## Chatterbox through the inference worker (S4.3, 2026-10-11)

Question: does the integrated path (application API, then the separate worker over HTTP, then the quality
gate and storage) work with the real model, and what does the extra hop cost?

Setup: the application's own API (`/voice/upload`, `/synthesize`, `DELETE /voice/profiles/...`) with
`TTS_ENGINE=chatterbox_nano`, the real Nano worker on the RTX 4060 over loopback HTTP, one real LibriSpeech
speaker (one reference clip uploaded), four texts. The worker ran from a **fresh virtual environment built
from `tts_worker/requirements.lock.txt`**, not the environment used for the benchmarks.

| Text | Audio | Request time | End-to-end RTF | Similarity to the real speaker |
|---|---|---|---|---|
| 31 characters (first request, includes warm-up) | 1.84 s | 1.47 s | 0.80 | 0.815 |
| 61 characters | 3.40 s | 0.55 s | 0.16 | 0.846 |
| 142 characters | 7.72 s | 0.99 s | 0.13 | 0.896 |
| 460 characters, 30.9 s of speech | 30.88 s | 4.23 s | 0.14 | 0.887 |

Every reply was 24 kHz. Reading the reference, the HTTP hop, the gate and levelling add little: the
end-to-end factor (0.13 to 0.16) is close to the model's own 0.12. After five requests the worker had left
no temporary files and its log held none of the request texts; deleting the profile removed every upload file.
The S3.4 quality gate, calibrated on SV2TTS, passes all 180 Chatterbox outputs from the benchmarks (duration
ratios 0.78 to 1.43), so it needed no recalibration. A worker built from the lock file answered health and an
authenticated synthesis (24 kHz float WAV).

### Limits

* One speaker, one model (Nano), four texts, loopback network. A remote worker adds network latency and sends about 640 KB of reference per request.
* **Long text can be cut silently.** The 460-character text produced 30.9 s of speech; the model samples at most
  1000 speech tokens (about 40 s). A denser 500-character text may be cut with no signal: the worker reports
  no truncation, so only the gate's duration check can notice.
* No fallback to SV2TTS when the worker is down yet (plan S4.4): the request gets a 503 and a failed audit row.
* The worker image (`tts_worker/Dockerfile`) is unbuilt. The lock has no hashes (two requirements install from Git commits).
* In this harness `/health/ready` returned 503 only because my scratch SQLite database had no `alembic_version`
  table; the engine block itself showed the worker reachable.

## Worker outage and the fallback (S4.4, 2026-10-11)

Question: when the Chatterbox worker goes away, do users still get speech, and does service come back by itself?

Setup: the real pipeline with the real SV2TTS weights on the CPU as the fallback, the real Nano worker (built
from its lock file) on the GPU, `TTS_WORKER_BREAKER_FAILURES=3`, cooldown 8 s. One speaker, one 52-character
sentence, ten requests in sequence while the worker was started, killed and started again.

| Request | State | Served by | Time | Circuit afterwards |
|---|---|---|---|---|
| 1 to 2 | worker up | Chatterbox, 24 kHz | 1.32 s, 0.53 s | closed |
| 3 to 4 | worker killed | **SV2TTS, 16 kHz** | 6.7 s, 6.3 s | closed |
| 5 | still down | SV2TTS | 6.5 s | **open** (third failure) |
| 6 to 7 | still down | SV2TTS | 7.1 s, 6.5 s | half-open, then open again |
| 8 | down, after the cooldown | SV2TTS | 6.5 s | open (the probe failed) |
| 9 | worker restarted, after the cooldown | **Chatterbox, 24 kHz** | 1.34 s | **closed** (the probe worked) |
| 10 | worker up | Chatterbox | 0.51 s | closed |

Every request was answered; none became an error. Service returned without any operator action.

### What this shows and what it costs

* The fallback works end to end, and the breaker opens, probes and closes as designed.
* **The fallback is slow and lower quality**: about 6.5 s against 0.5 s (about 13 times slower, on this CPU with
  24 cores) and 16 kHz against 24 kHz. A user during an outage gets a worse voice later, not an error. Every
  such request is logged and counted (`clonevoice_engine_fallback_total`), and nothing tells the user.
* A refused connection fails instantly, so this run does not show the breaker's main benefit, which is skipping
  a **blackholed** worker whose connect would otherwise wait the full connect timeout (5 s) on every request.
  The 26 tests cover it with a fake clock; it was not measured against a network that drops packets.

### Limits

* One speaker, one text, one machine. The fallback is slower on a smaller CPU: with 8 threads SV2TTS ran at
  1.9 times real time in S4.2b.
* Only an unavailable worker triggers the fallback. A worker that answers with bad audio is handled by the
  quality gate (retry, then a 502), not by SV2TTS.
* The user is not told which engine served them, and the generation row does not record it (plan S7.1).
* A worker that dies mid-request surfaces as a timeout or reset, which counts as unavailable; the request is served by the fallback after waiting up to `TTS_WORKER_TIMEOUT_SECONDS` (25 s by default).

## Independent speaker encoder and predicted naturalness (S0.1d, 2026-10-11)

Question: do the S4.2 conclusions survive measurement by instruments the engines were not built with?
Until now speaker similarity was judged by resemblyzer, the encoder that conditions SV2TTS (which flatters
SV2TTS), and naturalness was not measured at all. Both are now added to the committed scoring tool
(`backend/score_engine_outputs.py --independent-encoder ecapa --mos utmos`, optional, evaluation only) and the
same 240 outputs of the S4.2 benchmark (4 engines x 6 speakers x 10 texts) were scored again.

* **Independent encoder**: SpeechBrain ECAPA-TDNN (Apache-2.0, trained on VoxCeleb), cosine against the mean
  embedding of the speaker's real held-out clips. Its absolute values are not comparable with resemblyzer's.
* **Predicted naturalness**: UTMOS22 strong (SpeechMOS, code MIT; the weights' own licence is not stated on its
  page, which matters only because it never ships in the product). Audio is resampled to 16 kHz inside the model.

| Engine | Similarity, resemblyzer | Similarity, ECAPA | Predicted MOS | Word error |
|---|---|---|---|---|
| SV2TTS | 0.763 [0.741, 0.784] | 0.307 [0.271, 0.342] | 2.49 [2.31, 2.66] | 0.178 |
| Chatterbox 0.5B | 0.869 | 0.624 [0.590, 0.656] | 4.16 [4.08, 4.24] | 0.017 |
| Chatterbox-Turbo | 0.856 | 0.584 [0.551, 0.617] | 4.11 [4.02, 4.20] | 0.003 |
| Chatterbox-Nano | 0.856 | 0.580 [0.546, 0.616] | 4.14 [4.06, 4.21] | 0.005 |

Paired against SV2TTS on the same speaker and text:

| Engine | Resemblyzer gain | ECAPA gain | Predicted-MOS gain |
|---|---|---|---|
| Chatterbox 0.5B | +0.106 (56 of 60) | **+0.316** [+0.283, +0.350] (60 of 60) | **+1.68** [+1.53, +1.83] (60 of 60) |
| Turbo | +0.092 (52 of 60) | +0.277 [+0.246, +0.308] (59 of 60) | +1.63 [+1.47, +1.79] (60 of 60) |
| Nano | +0.093 (53 of 60) | +0.273 [+0.240, +0.305] (58 of 60) | +1.65 [+1.49, +1.82] (60 of 60) |

Voice-group fairness (low-pitch against high-pitch speakers, mean similarity):

| Engine | Gap, resemblyzer | Gap, ECAPA | ECAPA low / high |
|---|---|---|---|
| SV2TTS | 0.072 | **0.107** | 0.361 / 0.254 |
| Chatterbox 0.5B | 0.020 | 0.029 | 0.609 / 0.638 |
| Turbo | 0.031 | 0.020 | 0.574 / 0.594 |
| Nano | 0.022 | 0.020 | 0.570 / 0.590 |

### What this shows

* **The earlier conclusion holds and was understated.** A different encoder finds the Chatterbox gain about three
  times larger than resemblyzer did, in 58 to 60 of 60 pairs. The resemblyzer-only numbers were conservative,
  as expected from a judge that shares its encoder with the baseline.
* **Naturalness clears the plan's target for every Chatterbox variant** (predicted MOS at least 3.8; they score
  4.1 to 4.2) and SV2TTS does not (2.49). Turbo and Nano are indistinguishable from the original on this measure.
* **The fairness finding is stronger with the independent encoder**: SV2TTS is clearly worse for high-pitched
  voices (gap 0.107, over the plan's 0.05 limit), while all three Chatterbox variants stay at or under 0.03.
* The 12 SV2TTS outputs with a word error above 0.3 average a predicted MOS of 1.4, against 2.8 for the rest, so the
  predictor notices the broken ones.

### Limits

* **A predicted MOS is not a listening test.** UTMOS was trained on the Blizzard and Voice Conversion Challenge
  ratings, which are of synthetic English speech; it can reward clean, steady audio and it cannot judge identity
  or expressiveness. The plan says only the listening test decides release, and none has been run.
* ECAPA was trained on VoxCeleb (celebrity interview speech); other engines' voices were not tested on it
  beyond this corpus. Absolute similarity values mean little; the paired differences are what to read.
* Six adult speakers (3 low-pitch, 3 high-pitch), ten texts, one seed; no children or elderly voices.
* Still no emotion classifier: whether any engine speaks with the requested emotion is unmeasured.
* The new tools need `speechbrain`, `torch` and a network download of the UTMOS weights (about 390 MB); they are not
  in `requirements-dev.txt`, for the same reason `faster-whisper` is not.

## Best-of-N candidate selection (S2.5, 2026-10-13)

`python -m backend.evaluate_synthesis --best-of 3`: the production pipeline with `TTS_BEST_OF_N` 1 against 3, same seed
per sentence (so the first candidate is identical and the pair isolates the selection). 12 LibriSpeech test-clean speakers
(7 high-F0, 5 low-F0), 4 sentences each, scored against the speaker's held-out real clips.

| Metric | N=1 | N=3 | Paired change (95% CI) | Speakers improved |
|---|---|---|---|---|
| Speaker similarity, resemblyzer | high 0.724, low 0.753 | high 0.743, low 0.776 | **+0.021** (+0.013 to +0.028) | 11 of 12 |
| Median-style F0 error (semitones, lower is better) | high 5.4, low 1.9 | high 5.1, low 2.0 | -0.14 (-1.11 to +0.83), no effect | error fell for 8 of 12 |

* The similarity gain is real but small, and is **judged by the encoder that does the selecting**, so it is flattered: the
  selection optimises that very score. An independent encoder (ECAPA) could not be installed in this environment
  (`torchaudio` has no build matching `torch 2.13`), so the gain on an independent judge is unmeasured.
* Pitch error does not move, in line with the S2.1a finding: the pitch weakness belongs to the model.
* Cost: about 2.9 times the latency at N=3 (6.2 s to 17.9 s for one sentence on this CPU).
* Twelve adult speakers, one seed, no listening test.

## Room reverb and the upload hint (S2.2b, 2026-10-14)

`evaluate_synthesis --degrade-compare` gained simulated room reverb (decaying-noise impulse
response, direct path plus a -6 dB tail; `add_reverb`). 10 LibriSpeech test-clean speakers, one
seed, clone similarity on the model's own encoder (resemblyzer), change against the clean clip:

| Defect | Change | Speakers worse |
|---|---:|:---:|
| reverb RT60 0.3 s / 0.6 s / 1.0 s | -0.037 / -0.056 / -0.053 | 8 / 8 / 7 of 10 |
| noise 20 / 10 / 5 dB (same run) | -0.049 / -0.084 / -0.102 | 9 of 10 each |
| telephone band; clipping x8 | -0.021; -0.068 | 7; 9 of 10 |

Reverb costs as much as the noise-20 dB and mild-clipping cases that already carry a warning, so it
gets a warning. The measure (`decay_drop_db`) is the 90th percentile of how far the level falls in
80 ms from frames near the loud speech level: dry speech falls 20+ dB at word ends, a room fills the
gap. On 240 clean clips (5th percentile 12.8 dB) the warning level of 12.5 dB flags 4.6%; simulated
rooms: RT60 0.2 s 5.8%, 0.3 s 17.5%, 0.4 s 31%, 0.6 s 80%, 1.0 s 99%. Noise also lowers it (10 dB SNR
flags 69%), which is why noise is hinted separately and is the likelier fix.

Limits: the room is simulated (a real recording room differs), mild reverb (RT60 under 0.4 s) is mostly
missed, thresholds were chosen and checked on the same corpus, and clone similarity is judged by the
model's own encoder.

## Emotion accuracy of the SV2TTS baseline (S0.3, 2026-10-20)

First real run of the emotion classifier (`superb/wav2vec2-base-superb-er`, 4 classes) on the
20-speaker LibriSpeech corpus (10 `adult_low_f0`, 10 `adult_high_f0`, rebuilt with
`prepare_eval_corpus`), current `main` (`05d7633`), CPU, real weights, seed 1234:

```bash
python -m backend.evaluate_synthesis --data-dir <corpus> --groups <corpus>/groups.json --speakers 20 \
  --stems 5 --emotions 10 --emotion-classifier superb --whisper-model none --paragraphs 0 --typed 0
```

Each speaker clones 10 emotional sentences in their neutral, happy, sad and angry renderings (40 clips;
800 in all). SV2TTS has no emotion input, so the four renderings differ only in wording.

| | All (n=20) | adult_low_f0 | adult_high_f0 | Plan target |
|---|---|---|---|---|
| **Emotion accuracy** | **0.314** (251 / 800) | 0.348 [0.305, 0.390] | 0.280 [0.235, 0.332] | ≥ 0.70 |
| Recall: neutral | 0.15 | 0.22 | 0.08 | |
| Recall: happy | 0.52 | 0.72 | 0.32 | |
| Recall: sad | 0.19 | 0.22 | 0.16 | |
| Recall: angry | 0.40 | 0.23 | 0.56 | |

Confusion (rows = requested, columns = heard; 200 clips per row):

| requested \ heard | neutral | happy | sad | angry |
|---|---:|---:|---:|---:|
| neutral | 30 | 103 | 1 | 66 |
| happy | 11 | 104 | 4 | 81 |
| sad | 8 | 74 | 38 | 80 |
| angry | 3 | 109 | 9 | 79 |

### What this shows

* **Baseline recorded: 31% against a 25% chance level and a 70% target.** SV2TTS cannot be told what
  to feel, and the number agrees: the text alone moves the heard emotion very little.
* **The classifier mostly answers "happy" or "angry"** (390 and 306 of 800 predictions; only 52 each for
  neutral and sad), whatever was requested. So the per-label recalls are shaped by that bias as much as
  by the voice. A sad sentence is heard as sad 19% of the time and as happy or angry 77%.
* **The two voice groups answer differently** (low voices are heard as happy, high voices as angry),
  which is a classifier-by-pitch interaction, not evidence about the synthesiser.
* The accuracy is the figure to beat for S5; read gains against this baseline, not against 70%.

### Limits

* **The classifier is a coarse, biased judge.** It is trained on acted English speech (IEMOCAP), 4 classes,
  and gives near-constant answers on this synthetic speech. It has no positive control: it was not run on
  real emotional recordings here, so its own accuracy on natural speech is unknown.
* Adults only, one seed, n = 10 per group (intervals are over speakers).
* **The other metrics in this run did not match the S0.4 record** (similarity 0.74 against 0.760, `?` rise
  0.40 against 0.52, pitch range ratio in the high group 0.89 against 0.62). This run is on current `main`
  (S1 to S3 changes since `f4d8cbe`: pauses, loudness, limiter, quality gate with retries) and a different
  stimulus mix, so it is not a reproducibility failure. Determinism was checked on a subset only: two runs of
  2 speakers with the same seed gave identical rows and confusion. The full 20-speaker run was then
  repeated (S0.1e below) and matched on every seeded metric and every emotion label.
* No predicted MOS, RTF, WER or independent encoder in this run (`faster-whisper` and `speechbrain` are
  not installed here).

## Predicted naturalness and real-time factor of the SV2TTS baseline (S0.1e, 2026-10-20)

The S0.3 run repeated with `--mos utmos` on the same 20-speaker corpus, current `main` (`c6e716a`) plus the
new `rtf` and `mos` columns, CPU (16 threads), real weights, seed 1234, 816 syntheses:

```bash
python -m backend.evaluate_synthesis --data-dir <corpus> --groups <corpus>/groups.json --speakers 20 \
  --stems 5 --emotions 10 --emotion-classifier superb --whisper-model none --paragraphs 0 --typed 0 --mos utmos
```

| | All (n=20) | adult_low_f0 | adult_high_f0 | Plan target |
|---|---|---|---|---|
| **Predicted MOS** (UTMOS22, mean per speaker over its clips) | **3.01** (2.31 to 3.49) | 3.15 [3.02, 3.27] | 2.88 [2.68, 3.07] | ≥ 3.8 |
| **RTF** (compute seconds per audio second, pooled per speaker) | **3.02** (2.44 to 3.66) | 3.07 [2.83, 3.28] | 2.98 [2.71, 3.24] | within `INFERENCE_CALL_TIMEOUT_SECONDS` at the maximum text length |

Group gap in MOS is 0.27 (the fairness limit in the plan is stated for similarity, 0.05; there is no MOS limit).

**Determinism:** every seeded metric (similarity, pitch error, pitch range, spectrum distance, `?` and `!`
contrast, emotion labels) is identical to the S0.3 run for all 20 speakers, so the fixed-seed gate holds on the
full run. RTF and MOS are timings and a model output, not seeded; MOS was not repeated.

### What this shows

* **SV2TTS is 0.8 MOS below the plan's naturalness target** (3.01 against 3.8), and high voices are rated
  lower than low voices (2.88 against 3.15). The S0.1d score of the 240 S4.2 outputs (SV2TTS 2.49, Chatterbox
  4.1) used other texts and speakers, so it is not the same number; both say the baseline engine is the weak one.
* **On this CPU the pipeline takes about 3 s of compute per second of speech.** Speech
  takes about three times as long to generate as to play, so any text longer than a few seconds of audio
  is slower than real time on this machine (whether that breaks `INFERENCE_CALL_TIMEOUT_SECONDS`, 30 s per
  stage, at the maximum text length was not measured here). It includes the quality gate's retries and the pipeline's own file write, so it is
  the latency a request sees, not the vocoder alone. It does not include the UTMOS or emotion scoring.

### Limits

* **A predicted MOS is not a listening test.** UTMOS is trained on synthetic-speech ratings, cannot judge
  identity or expressiveness, and its weights have no stated licence (evaluation only).
* **RTF is one machine**: a 16-thread development CPU, with nothing else running. The target host (Railway) is
  unmeasured, and the number moves with thread count. Clips are short
  (single sentences), so fixed per-request costs weigh more than they would on paragraphs. The S0.3 run was not timed.
* A two-speaker smoke run measured 2.3 here against 3.0 over the full run, so run-to-run spread is wide; treat
  the third digit as noise. One seed, adults only, n = 10 per group.
* `torchaudio` has no build for this venv's torch (2.13), so a stub stands in for its `resample` (identity at
  16 kHz); UTMOS scores were not checked against a real `torchaudio`.

## Word error rate of the SV2TTS baseline on the full corpus (S0.4b, 2026-10-21)

The multi-sentence stimuli of S0.1c run on the full 20-speaker corpus with Whisper `small.en`, current `main`
(`e8426e3`), CPU (16 threads, otherwise idle), real weights, seed 1234, 160 syntheses (4 paragraphs and 4 typed
texts per speaker), with `--mos utmos` so the same run also gives MOS and RTF on longer texts:

```bash
python -m backend.evaluate_synthesis --data-dir <corpus> --groups <corpus>/groups.json --speakers 20 \
  --skip-single --paragraphs 4 --typed 4 --mos utmos --whisper-model small.en --seed 1234
```

| | All (n=20) | adult_low_f0 | adult_high_f0 | Plan target |
|---|---|---|---|---|
| **WER, paragraphs** (mean per speaker) | **4.7 %** (0 to 24.6 %) | 3.0 % [1.0, 5.4] | 6.5 % [2.4, 11.3] | ≤ 5 % |
| **WER, typed texts** (numbers, abbreviations) | **9.6 %** (3.4 to 19.2 %) | 7.8 % [6.7, 9.3] | 11.4 % [8.6, 14.2] | ≤ 5 % |
| **Predicted MOS** (UTMOS22) | **2.77** (2.23 to 3.34) | 2.93 [2.79, 3.07] | 2.61 [2.42, 2.81] | ≥ 3.8 |
| **RTF** | **2.27** (1.75 to 2.74) | 2.36 [2.23, 2.48] | 2.17 [2.01, 2.35] | within `INFERENCE_CALL_TIMEOUT_SECONDS` |
| Speaking rate (s per word) | 0.352 | 0.352 | 0.352 | |
| Pauses per paragraph / mean pause (s) | 2.14 / 0.50 | 2.05 / 0.51 | 2.23 / 0.50 | |

Group gaps: WER 3.5 points (paragraphs) and 3.6 points (typed), both within the plan's limit; MOS 0.31 and RTF
0.19, both over it (there is no limit for either in the plan).

### What this shows

* **Paragraph WER meets the 5 % target on average, but not for every voice.** The median speaker is at 1.8 %;
  the mean is pulled up by a few speakers, the worst being 237 (24.6 % on paragraphs, high F0). High voices are
  at 6.5 % against 3.0 % for low voices, and the intervals overlap, so the gap is a lead, not a finding.
* **Typed texts are twice as hard (9.6 %) and miss the target for both groups.** These are the texts with
  numbers and abbreviations; how much of that error is the synthesiser and how much is Whisper normalising
  digits and spellings differently from the reference was not separated.
* **MOS and RTF on paragraphs differ from the single-sentence numbers of S0.1e** (2.77 against 3.01, 2.27
  against 3.02): different texts, so the two runs are not comparable. The same ordering holds (high voices rated
  lower), and SV2TTS stays about 1 MOS under the 3.8 target.

### Limits

* **WER is measured by one ASR model** (`small.en`), which has its own errors; a clean speaker at 0 % and a
  worst case at 24.6 % come from 4 paragraphs each, so a single bad take moves a speaker's mean a lot.
* **The speaker-similarity judge is the model's own encoder** (`resemblyzer`), not independent; similarity
  is not in this run's output (the single-sentence study that reports it was skipped with `--skip-single`).
* **RTF is one machine**, as in S0.1e. One seed, adults only, n = 10 per group.
* Not repeated: this run was not compared with a second run of the same seed, so determinism of WER was not
  re-checked here (the seeded gate was held in S0.4 and S0.1e).

## Independent speaker similarity of the SV2TTS baseline (S0.1f, 2026-10-22)

The single-sentence study repeated with `--independent-encoder ecapa`, which adds an `ecapa` column: the same
cosine as `secs`, but computed by SpeechBrain ECAPA-TDNN (VoxCeleb) instead of the encoder that conditions the
synthesizer. Same 20-speaker corpus, current `main` (`dcecf60`) plus the new column, CPU (16 threads), real
weights, seed 1234, in a separate venv with torch 2.6 and a real `torchaudio` (the main venv's torch 2.13 has no
matching build, and a stubbed one gives wrong ECAPA embeddings: cosine 0.02 against the real ones):

```bash
python -m backend.evaluate_synthesis --data-dir <corpus> --groups <corpus>/groups.json --speakers 20 \
  --independent-encoder ecapa --whisper-model none --paragraphs 0 --typed 0 --seed 1234
```

| | All (n=20) | adult_low_f0 | adult_high_f0 | Gap | Plan target |
|---|---|---|---|---|---|
| **`secs`**, resemblyzer (the model's own encoder) | **0.710** [0.666, 0.748] (0.50 to 0.82) | 0.753 [0.717, 0.785] | 0.668 [0.604, 0.728] | 0.084 | gap ≤ 0.05 |
| **`ecapa`**, independent | **0.290** [0.234, 0.341] (-0.01 to 0.49) | 0.337 [0.276, 0.387] | 0.244 [0.152, 0.335] | 0.093 | gap ≤ 0.05 |

Per-speaker correlation of the two scores: r = 0.80. `within_gap_limit` is false for both.

### What this shows

* **The model's own judge flatters it by a wide margin: 0.71 against 0.29.** The two scales are not comparable
  (S0.1d: read paired differences, not absolute values), but the plan's SECS target is stated on an independent
  encoder, so the absolute `secs` figures of S0.4 and later say little about it.
* **Both encoders find the same weakness.** High-pitch voices are cloned worse (gap 0.084 and 0.093), the
  ordering agrees on 20 speakers (r = 0.80), and the fairness limit of 0.05 is missed under either judge. The
  intervals overlap at n = 10 per group, so this is a lead, not a finding.
* **One clone does not sound like its speaker to either judge:** speaker 1284 (high F0) scores 0.50 on
  resemblyzer, the lowest of the 20, and -0.01 on ECAPA. The next worst on ECAPA are 3729, 4970 and 8224 (0.08
  to 0.13), all also in the lower half on resemblyzer.

### Reproducibility check

`secs` is 0.710 here, against 0.760 in the S0.4 record and 0.74 in the S0.3 run on the same `main`. The S0.4
number predates the S1 to S3 changes, which S0.3 already showed move it. The remaining 0.03 against S0.3 may be
the torch version (2.6 here, 2.13 there); this was **not** isolated, so it is stated as unexplained. The `ecapa`
column has no earlier run to compare with.

### Limits

* ECAPA was trained on VoxCeleb (celebrity interview speech) and its absolute values are not a percentage of
  anything; it is a second opinion, not ground truth. Only the listening test decides.
* The run was in a different environment (torch 2.6, `PYTHONPATH` overlay) from the other S0 runs, so
  differences in `secs` and the other columns of this report are not attributed to the code.
* One seed, adults only, n = 10 per group, one reference clip per speaker. `speechbrain` and the 390 MB ECAPA
  weights are not in `requirements-dev.txt`.
* Only the single-sentence study carries `ecapa`; the independent column is rejected with `--skip-single`
  instead of being silently dropped.

## Positive control for the question metric (S0.3b, 2026-10-22)

The `?` metric (final pitch slope over the last 0.3 s) reads about chance on SV2TTS output (52 %). That reading
only means something if the metric separates real questions from real statements, so it was run on **human**
speech: LibriSpeech test-clean (`0000.parquet`, 2620 utterances) with `python -m backend.question_control`.
LibriSpeech transcripts have no punctuation, so the labels are a heuristic on the words: **question** = 4 to 15
words, opens with an auxiliary and a pronoun ("DO YOU", "IS IT"), no speech attribution ("SAID", "ASKED"); **statement**
= 4 to 15 words, opens with neither an auxiliary nor a wh-word, no attribution (a seeded sample of 300).
Wh-questions are left out on purpose, they often fall in pitch.

| | n | Mean final slope (semitones/s) | Share rising | AUC, question above statement |
|---|---|---|---|---|
| **Yes/no questions** | 21 | -0.4 [-12.1, 8.6] | **76 %** | **0.67** [0.53, 0.79] |
| Statements | 297 | -6.1 [-8.3, -3.7] | 38 % | |

Sensitivity (decided after reading the 21 labelled questions, so post hoc): dropping the 3 subjunctive wishes
("WERE I BUT...", "MAY YOU...") gives n = 18, AUC 0.69 [0.56, 0.81]; also dropping the 2 whose question is followed
by a few words of narration ("...I SUSPECT", "...I WENT ON") gives n = 16, AUC 0.74 [0.61, 0.85]. The interval stays
above 0.5 in every variant.

### What this shows

* **The metric separates real questions from real statements, but only moderately.** A question ends on a
  higher slope than a statement about two times in three (AUC 0.67 to 0.74); 76 % of the questions rise
  against 38 % of the statements. It is not chance, so the 52 % on SV2TTS is not just a broken metric.
* **Read the 52 % as "SV2TTS does not mark the question", with a caveat.** Real speech, which the metric sees
  as roughly 0.7, is the reference the model should be compared with; the model's 52 % is a different
  statistic (the same sentence typed with `?` against `.`), so the two numbers are not on one scale.
* **The plan's target of 80 % for `?` is above what real speech reaches here** (76 % of labelled questions
  rise): it is a ceiling the metric may not be able to show, so recalibrate it before treating a miss as a model fault.

### Limits

* **The labels are a word heuristic on unpunctuated text:** 21 questions, a few of them not questions or
  ending in narration. The interval is wide (0.53 to 0.79).
* **Book reading is not conversation.** Readers voice questions flatter than speakers do, which would
  understate the contrast; the result applies to this metric on read English only.
* Yes/no questions only; wh-questions and tag questions were not tested. Adult readers, one file, one seed.
* A cleaner control needs punctuated read speech (for example LibriTTS, CC BY 4.0, a download), which was not fetched.

## Elderly adult speakers against a same-source control (S0.2b/S0.2c/S0.2d, 2026-10-23)

First real run of the Common Voice builder. Data: Common Voice Scripted Speech 26.0, **American English (Male)** subset
(MDC Curators, CC0-1.0, accents exactly "United States English", gender `male_masculine`), shipped as speaker-disjoint
`train.tsv`/`dev.tsv`/`test.tsv` with no `validated.tsv`, which `prepare_cv_corpus` now reads (S0.2c, `a23b826`). The
subset holds 176 speakers in their sixties, 67 in their seventies and 9 in their eighties. Ten speakers per group were
chosen (`--per-group 10`), named by a hash of `client_id`, and written to a scratch directory outside the repository
(the licence forbids re-hosting and identifying speakers). `elderly` is sixties and seventies; `cv_adult_control` is
twenties to forties; both come from the same crowd-sourced recordings, so only age differs. Same recipe and
environment as S0.1f (torch 2.6, real `torchaudio`, CPU, real weights, seed 1234):

```bash
python -m backend.evaluate_synthesis --data-dir <corpus> --groups <corpus>/groups.json --speakers 20 \
  --independent-encoder ecapa --whisper-model none --paragraphs 0 --typed 0 --seed 1234
```

| | elderly (n=10) | cv_adult_control (n=10) | Gap | Within limit |
|---|---|---|---|---|
| `secs`, resemblyzer | 0.699 [0.658, 0.742] | 0.733 [0.702, 0.758] | 0.033 | yes (0.05) |
| `ecapa`, independent | 0.292 [0.233, 0.349] | 0.319 [0.259, 0.377] | 0.026 | yes (0.05) |
| spectral distance, dB (lower is better) | 6.52 [5.59, 7.43] | 5.60 [4.56, 6.59] | 0.93 | no |
| F0 error, semitones | 1.89 [0.56, 3.53] (n=8) | 2.13 [1.22, 3.17] | 0.24 | no |
| F0 range ratio | 0.652 [0.397, 0.906] (n=8) | 0.561 [0.421, 0.725] | 0.09 | no |
| question-rise rate | 0.578 [0.467, 0.711] (n=9) | 0.365 [0.260, 0.490] | 0.21 | no |
| exclamation-lift rate | 0.244 (n=9) | 0.245 | 0.001 | yes |
| RTF | 3.41 | 3.51 | 0.10 | no |

### What this shows

* **Elderly adult male voices are cloned about as well as younger ones on both judges.** The gaps (0.033 and 0.026)
  are inside the 0.05 limit, the intervals overlap, and the ECAPA mean (0.292) matches the LibriSpeech baseline
  (0.290, S0.1f). At n = 10 this is the absence of a detectable difference, not proof of none.
* **The one lead is spectral distance:** 6.52 dB for elderly against 5.60 dB (gap 0.93 dB, outside the plan's limit,
  intervals overlapping). It may reflect aged voice quality (breathiness, roughness) being reproduced less well;
  this was not tested.
* `secs` here (0.70 to 0.73) is not comparable with the LibriSpeech 0.71 of S0.1f: different corpus, microphones and
  codec. Only the elderly-against-control contrast is meaningful.

### Limits

* **Adult male speakers only.** The subset is male; nothing here says anything about elderly women, and no claim is
  made for them. Children remain out of scope (decision Q4).
* n = 10 per group, one seed, one reference per speaker; most intervals overlap. F0 metrics have 8 or 9 elderly
  speakers because the pitch tracker returned no value for the others.
* Age is self-declared and the oldest Common Voice band is the seventies and eighties; speakers with enough clips
  to qualify may be frequent contributors.
* No word error rate (`--whisper-model none`), no listening test.

### Elderly women (same recipe, 2026-10-23)

Same procedure on the **American English (Female)** subset (MDC Curators, CC0-1.0, gender `female_feminine`; 136 speakers
in their sixties, 41 in their seventies and 6 in their eighties). Ten speakers per group, seed 1234, no code change.

| | elderly (n=10) | cv_adult_control (n=10) | Gap | Within limit |
|---|---|---|---|---|
| `secs`, resemblyzer | 0.669 [0.625, 0.711] | 0.677 [0.640, 0.711] | 0.008 | yes (0.05) |
| `ecapa`, independent | 0.261 [0.148, 0.362] | 0.203 [0.155, 0.254] | 0.058 | no |
| spectral distance, dB (lower is better) | 6.10 [5.54, 6.64] | 6.96 [5.90, 8.04] | 0.86 | no |
| F0 error, semitones (range-agreement check, S0.2h) | 2.94 [1.20, 4.75] (n=6) | 1.94 [1.22, 2.76] (n=7) | 1.00 | no |
| F0 range ratio (range-agreement check) | 0.864 [0.479, 1.234] (n=6) | 0.765 [0.279, 1.428] (n=7) | 0.10 | no |
| clone voiced fraction | 0.455 [0.277, 0.621] | 0.542 [0.370, 0.697] | 0.09 | no |
| question-rise rate | 0.553 [0.433, 0.683] | 0.390 [0.310, 0.470] | 0.16 | no |
| RTF | 3.74 | 3.58 | 0.16 | no |

What this shows:

* **Resemblyzer finds no age gap for women (0.008). ECAPA's gap (0.058) points the other way from the men's:** elderly women
  score higher (0.261) than the younger control (0.203). The intervals overlap, so this is not a finding that elderly
  women are cloned better; it does show the age effect is not a consistent deficit across the two groups.
* **Women score lower than men on both judges:** ECAPA 0.20 to 0.26 against 0.29 to 0.32, secs 0.67 to 0.68 against
  0.70 to 0.73. The groups come from different speakers and corpora, so this is a lead, not a gender comparison.
* **Re-scored twice (S0.2e guard, then S0.2h range-agreement check; secs, ECAPA, spectral distance, question rate and voiced
  fraction reproduced to the last digit each time).** Three control and two elderly clones have no F0 error because too
  little of the clone is voiced (voiced fractions 0.00 to 0.27 against 0.4 to 0.85 for the rest). Two more elderly
  speakers, `109292d3b481` (41.8 semitones) and `062a915b1870` (22.0), were found in S0.2g to be a tracker lock on a
  constant tone in the real recordings and a clone with no stable pitch; the S0.2h check, which rejects a track whose median
  moves more than 2 semitones between search ranges, now excludes both. **The elderly F0 error is 2.94 [1.20, 4.75] (n=6)
  against 1.94 [1.22, 2.76] (n=7) for the control: a difference of about 1 semitone with overlapping intervals, so no age
  effect on pitch is detectable for women either.** The earlier 10.17 was two bad measurements, not a pitch result.
  Only six of ten elderly and seven of ten control clones are measurable, so the claim rests on small samples.
* **Clones of some women are largely unvoiced.** The elderly clone of `09d129e07097` has voiced fraction 0.00 yet ECAPA 0.45,
  the opposite of what an unvoiced clone should score; nobody has listened to it. Whether these are synthesis faults or tracker
  failures is open.
* **The spectral-distance lead of the men does not reproduce:** elderly women are 0.86 dB *better* than the control, so
  there is no evidence that aged voice quality is reproduced worse in general.

Limits (in addition to those above): adult women only here, n = 10 per group, intervals mostly overlap; no word error
rate, no listening test. Nothing in this section covers children (decision Q4).

## Garbled endings and the speech-time gate check (S3.5, 2026-10-24)

Question: some clones are noisy and lose the last words of a sentence ("You are coming to the meeting."
heard as "You are"). How common is that, what causes it, and can the output gate catch it? All runs on
the GPU (RTX 4060), real weights, GPU recogniser (faster-whisper small.en); the fault also appears on CPU
(seen first there). Speakers are named by a hash of `client_id`; the audio stays in the scratch directory.

| Measurement | Result |
|---|---|
| 40 speakers x 6 seeds, one 6-word sentence (240 clips) | 22.5% of clips have WER 0.34 or worse; 71% are transcribed perfectly |
| 10 speakers x 40 sentences of 7 to 11 words (400 clips) | 28.5% bad (beam 1: 28.5%, beam 5: 28.2%) |
| Bad rate per speaker (same 40 sentences) | 100%, 85%, 53%, 23%, 10%, then five speakers at 0 to 7% |
| Reference recording SNR, same speakers | 29.6, 46.9, 44.0, 51.9, 44.7 dB for the five worst; 60 dB (the report's cap) for the five best |
| Noise added to a clean reference (3 speakers, white noise) | bad rate 0.8% clean, 5.8% at 30 dB, 22.5% at 20 dB, 26.3% at 10 dB |

Two listening rounds (10 clips each, one listener) agreed with the recogniser on 9 of 10 clips in the second
round. The listener heard noise that grew along the clip and "pale" or whispered last words, and called
two clips robotic and one too fast. The recogniser is the label used below; it slightly under-counts (it
completed one clip the listener heard as 3 words).

### What this shows

* **The fault is real and not rare:** a quarter of clips from Common Voice references lose or garble words,
  against 4.7% WER on the cleaner LibriSpeech speakers of S0.4b.
* **It follows the speaker, not the seed.** The worst speakers fail on nearly every sentence, so a retry with
  a new seed rarely rescues them.
* **Noise in the reference causes it, but unevenly.** Adding noise to clean references raised the bad rate from
  about 1% to 22% at 20 dB, one speaker to 50% and another to 12%. At 10 dB the pipeline's own gate refused one
  speaker outright (`duration_too_long`).
* **Failed clips run longer, not shorter.** Duration was the best cheap signal (AUC 0.86 to 0.93); whole-clip
  periodicity (0.75) and voiced share (0.81 to 0.86) were weaker; harmonic energy (0.53) was no use.

### The check that shipped

`check_output` gains `speech_too_long`: speech seconds (non-silent 20 ms frames, so typed pauses cannot inflate
it) divided by `-0.50 + 0.339 x words`, refused above 1.8, for texts of 6 to 11 spoken words
(`TTS_GATE_MAX_SPEECH_RATIO`, 0 turns it off). The existing duration check stayed as it was.

| On the 640 labelled clips | Result |
|---|---|
| Correct clips refused | 1 of 477 (0.2%) |
| Garbled clips caught | 36 of 163 (22.1%) |

### Limits

* **It catches about one garbled clip in five.** A wider net (ratio above 1.5) caught 43% but refused 2.1% of
  correct clips, a rate I judged too high for a check that ends in a refusal. The real fix is upstream: the
  enrolment check rated the worst speaker "good" (SNR 29.6 dB).
* **Fitted and tested on the same 640 clips**, 10 + 40 speakers, one sentence set, 7 to 11 words. The model has a
  negative intercept, so it is skipped outside 6 to 11 words; longer texts are not checked until chunk-level
  calibration is done.
* Labels come from one recogniser; the listening rounds had one listener and 20 clips.
* White noise only; real hum, room echo and compression were not tested.
* The unexplained case: `02b890a0449a` fails on 100% of sentences with a clean-looking reference.

### Does an enrolment threshold predict the failures? (S2.2e, 2026-10-24)

Question: would a stricter recording-quality warning at upload catch the speakers whose clones come out
garbled? Data: the 40 Common Voice speakers of the 6-word run (6 seeds each), the failure rate per speaker
(WER 0.34 or worse) against measures of the one reference clip used. 9 speakers fail on 30% or more of their
clips (8 on half or more); the other 31 are fine.

| Reference measure | Spearman with failure rate | AUC, failing vs. fine speakers |
|---|---|---|
| Estimated SNR | -0.33 | 0.72 |
| Level after decay (reverberation drop) | -0.32 | 0.78 |
| Agreement with the speaker's own other clips | -0.35 | 0.73 |
| Level (dBFS), high band, clipping, voiced seconds | between -0.17 and +0.24 | 0.50 to 0.59 |
| Pitch, embedding distance to the group centre | -0.11, +0.06 | 0.54, 0.55 |

What each SNR warning level would do on these speakers:

| Warn below | Failing speakers flagged (of 9) | Fine speakers flagged (of 31) |
|---|---|---|
| 25 dB (today) | 0 | 0 |
| 30 dB | 2 | 0 |
| 40 dB | 2 | 1 |
| 50 dB | 5 | 5 |
| 55 dB | 6 | 8 |

* **The existing check misses every failing speaker.** Today's rating was "good" for 6 of the 9 and "fair" for
  3; none was "poor". The worst speaker (`02b890a0449a`) had SNR 29.6 dB and no hint.
* **No threshold works.** Raising the SNR warning to 50 dB would flag 5 of the 9, and also 5 of the 31 fine
  speakers: half of the warnings would be wrong. No other measure does better. The 10-speaker lead from the
  earlier run (lower SNR, more failures) does not hold up at 40.
* **Noise itself is still a cause**, as the controlled test showed (added noise at 20 dB raised failures from
  about 1% to 22%), and today's 25 dB warning does flag that case. The real failing speakers are mostly not
  noisy by this measure, so the cause there is something these measures do not capture.
* **Decision: the thresholds stay as they are.** Changing them on this evidence would add false warnings and
  catch little.

Limits: 40 speakers and 9 failing ones; one reference clip per speaker; all measures are single-clip numbers.
What could work instead, untested: synthesize one short test sentence at upload and judge the result (costs a
synthesis per upload, and the speech-time check of S3.5 would catch about a fifth of the bad ones), or learn a
predictor from many more speakers.

### Larger speaker study and CPU check (S3.5b, 2026-10-24)

154 Common Voice speakers (79 men, 75 women; 76 elderly, 78 adult controls; 6 more were skipped for too few
usable clips), each cloned two ways: from one reference clip, and from four clips averaged the way the
product does (`aggregate_embeddings`). Six sentences of 7 to 11 words, the same seeds for both profiles,
GPU, the S3.5 gate on, scored by the recogniser (faster-whisper small.en). 1,848 clips.

| Profile | Clips with WER 0.34 or worse | Clips refused by the gate |
|---|---|---|
| One clip | 19.3% of 916 scored | 8 of 924 |
| Four clips averaged | 11.6% of 924 | 0 |

* **More clips help.** Paired by speaker, the bad rate falls 8.2 points (19.8% to 11.6%, 95% bootstrap
  interval -11.3 to -5.4; Wilcoxon p < 0.001). 45 speakers improved, 10 got worse, 99 were unchanged.
* **Age makes no difference:** elderly 19.3%, adult controls 20.3% (one clip). **Women fail more than men**
  in this data: 26.4% against 13.5% (one clip), 15.6% against 7.8% (four clips). Both are Common Voice
  recordings; whether the cause is gender or the recordings was not separated.
* **Recording measures still do not predict failure.** 44 speakers failed on 30% or more of their clips.
  AUC: SNR 0.69, agreement between the clips 0.68, level 0.64, band 0.61, pitch 0.58, reverb 0.53, voiced
  seconds 0.55, clipping 0.52. The enrolment rating was "good" for 101 speakers (29 failing) and "fair" for
  53 (15 failing): it carries no information. This confirms S2.2e at 154 speakers.
* **The speech-time check, tested on speakers it was not fitted on:** it refused 8 clips, all one-clip
  profiles, none correct. Re-synthesized with the check off, each of the 8 ran 6 to 8.5 s for about 9 words
  and scored WER 0.50 to 1.00. It also forced retries on about 9 more clips. But roughly 177 garbled clips
  were still served, so it catches under 10% of them, not the 22% it showed on the data it was fitted on.
  The 22% was optimistic. Its false refusals stayed near zero.
* **CPU matches GPU.** The first 20 speakers, one-clip profile, 6 sentences, synthesized on CPU: 17.8% bad
  against 18.6% on GPU, 2 refusals each, per-speaker bad rates correlate 0.92. Median synthesis was 6.0 s for
  3.5 s of audio (real-time factor 1.7, p90 10.5 s per clip) on this 24-thread desktop CPU. Railway's
  vCPUs will be slower, so a retry (a second full synthesis) costs more there.

Limits: Common Voice recordings only; one listener for all listening rounds; the recogniser is the label (it
under-counts slightly); four clips came from the speaker's own other sentences; the CPU check was 20 speakers
and one profile type; the speed figure is from this machine, not Railway.

What this means for the product: asking for several clips at upload (the product already accepts up to
`VOICE_MAX_SAMPLES`) is the one change measured to reduce garbled output, by about 40% relative. A stronger
upload prompt is the likely next step; the gate check helps little.

### Timing on Railway-sized CPUs (S3.5d, 2026-10-24)

Question: what does a request cost on the CPU-only container the product will run in? The real pipeline
(`run_inference_pipeline`, quality gate on, default timeouts) pinned to 8, 4, 2 and 1 logical CPUs with
`taskset` and the same thread count for torch (`TORCH_NUM_THREADS`), no GPU. 4 speakers, 5 requests each
(four 9-word sentences, one 38-word text of 10.8 s of audio).

| CPUs | 9-word sentence, median (p90) | Real-time factor | 38 words, 10.8 s of audio | Peak memory |
|---|---|---|---|---|
| 8 | 5.5 s (6.3) | 1.8 | 10.2 s | 1.7 GB |
| 4 | 7.5 s (8.5) | 2.4 | 14.7 s | 3.2 GB |
| 2 | 10.8 s (12.6) | 3.5 | 25.6 s | 4.6 GB |
| 1 | 11.8 s (14.4) | 4.0 | 28.0 s | 4.9 GB |

The vocoder is about 90% of the time. No gate retries happened in these 80 requests. Weights load in under
a second once cached.

The limits that matter more than the averages (defaults `INFERENCE_CALL_TIMEOUT_SECONDS` 30 s per stage,
`INFERENCE_ACQUIRE_TIMEOUT_SECONDS` 10 s, one inference at a time, text up to 500 characters):

| Test | 8 CPUs | 4 CPUs | 2 CPUs |
|---|---|---|---|
| One 488-character (95 word) request | served, 50.5 s | **fails** (vocoder over 30 s; 65.5 s before the error) | **fails** (34.0 s) |
| Three short requests at the same moment | 2 served (6.6 s, 12.8 s), 1 refused after 10 s | 2 served (8.5 s, 16.6 s), 1 refused after 10 s | 1 served (11.2 s), 2 refused after 10 s |

* **A maximum-length request fails on 4 CPUs or fewer**, and a second user is refused whenever the one
  ahead has not finished within 10 s, which at 2 CPUs is every short request.
* **After a request timed out, the next ones were refused while the slot stayed held.** This is the
  M6 hardening working as designed: the permit is kept until the abandoned worker thread returns, so two
  forward passes never overlap, but the thread cannot be killed and the vocoder ran on to the end. Measured
  after a 488-character request failed at 34 s: the slot stayed held another 20.4 s on 2 CPUs and 0.8 s on
  4 CPUs (S3.5e below).
* **Memory rose from 1.7 GB to 4.9 GB as threads fell.** Explained and fixed in S3.5g below: the output
  watermark, not the thread count.
* A gate retry doubles the cost of a request; none occurred here, so its real frequency on Railway is
  open (S3.5b: 25 first attempts in 1,848 requests).

Limits: this is an i7-13700HX (up to 5 GHz) with hyperthread pairs standing in for vCPUs. A cloud vCPU is
usually slower, so these times are a best case. One speaker pool, 20 requests per size, the concurrency test
was one run each, and the plan's own vCPU and memory limits were not checked against Railway.

What this suggests (not changed; these are settings and product decisions): on a small container, lower the
maximum text length or raise the stage timeout in proportion to the CPU count; and either lengthen the queue
wait or accept that simultaneous users will be turned away.

### Stopping abandoned passes early (S3.5e, 2026-10-24)

The synthesizer now checks, before each chunk, and the vocoder checks, at its existing progress hook every
100 steps, a flag that is set when the request that started the pass has given up (timeout or cancellation).
The pass then raises and the worker thread returns, so the permit is released within about a second. The
no-overlap guarantee is unchanged: the permit still goes back only when the thread has returned.

| 2 CPUs, one 488-character request that exceeds the 30 s stage limit | Before | After |
|---|---|---|
| Request fails after | 34.4 s | 34.1 s |
| Slot held after the failure | 20.4 s | 0.2 s |
| Next short request | served, 12.7 s | served, 12.7 s |

This does not make a too-long request succeed; it stops one slow request from refusing the users behind
it. Limits: one run per case, a fast desktop CPU, and the stage limit itself (30 s) and text maximum
(500 characters) are unchanged and still need a decision for the chosen Railway plan.

### Limits that follow the CPU (S3.5f, 2026-10-24)

The S3.5d timings showed a full-length text running past the 30 s stage limit on a small CPU, taking the
whole limit before failing. Measured with warm-up done (the earlier runs skipped it), the vocoder's cost is a
fixed part per call plus a part per second of audio, and it bends upward with length:

| CPUs | Fixed seconds per call | Seconds per second of audio |
|---|---|---|
| 2 | 6.5 | 1.09 |
| 4 | 4.7 | 0.63 |
| 8 | 3.6 | 0.41 |

Warm-up now times the vocoder at 1.5 s and 12.5 s of audio and keeps that pair. Each request is judged from
its text before it queues (estimated audio length from its words and typed pauses, then fixed + per-second x
audio against 30 s x `TTS_ADMISSION_MARGIN`). A text that would not fit is refused at once with a 422 that
names about how many words do (`TTS_ADMISSION_CONTROL`, default on). One-time cost: warm-up plus timing took
79 s on 2 CPUs and 106 s on 8 (including loading the models), inside the 600 s deploy health check.

| Real requests, warmed up, margin 0.8 | 2 CPUs | 4 CPUs | 8 CPUs |
|---|---|---|---|
| 20 words | served, 17 s | served, 13 s | served, 7 s |
| 40 words (13 s of audio) | served, 25 s | served, 18 s | served, 13 s |
| 60 words | refused at once (about 49 words fit) | served | served |
| 95 words (488 characters) | refused at once | refused at once (about 88 words fit) | served, 51 s |

* **A one-point timing was wrong.** Timing one short sentence gave 4.9 s per audio second on 2 CPUs, which
  would have refused texts that fit (the real figure at length is about 1.1). The fixed part dominates short
  audio.
* **A margin of 0.9 was too thin.** At 4 CPUs a 95-word text predicted at 25.6 s of vocoding still timed out
  (30 s limit, 66 s end to end); 0.8 refuses it. At 2 CPUs a 60-word text predicted at 23 s also timed out
  before the two-point fit was made longer.
* **The earlier "fails on 4 CPUs" in S3.5d was partly cold start:** those scripts skipped warm-up, which the
  service does at boot. Warmed up, 4 CPUs serve about 60 words and 8 serve the full 500 characters.
* **A gate retry still doubles the time.** A 60-word text hit the decode cap ("truncated") and the smaller
  chunk retry took 65 to 72 s in total on 4 CPUs. Retries are not in the estimate.

Limits: a fast desktop CPU with hyperthread pairs standing in for vCPUs (Railway's will be slower, which the
timing at boot captures by itself); one speaker; four to eight real requests per size; the estimate of audio
length is the S3.5 speech model (fitted on 6 to 11 word sentences) plus pauses, so its error on long text is
not measured; the 500-character API maximum is unchanged. The frontend now shows the lower limit before the user
presses Generate (S3.5i: `max_words` on `/synthesize/capabilities`, as an estimate that warns and never blocks).

### The memory growth was the watermark (S3.5g, 2026-10-25)

S3.5d recorded peak memory rising from 1.7 GB (8 CPUs) to 4.9 GB (1 CPU) and left it unexplained. Traced:

* **A clean process is small.** Models loaded: 0.7 to 0.8 GB; a 12.5 s vocoder call peaks at 1.2 to 1.3 GB,
  the same at 2 and at 8 threads. Run alone, the synthesizer and the vocoder each level off.
* **The full pipeline was not flat.** 30 requests (short sentences and a 38-word text every fifth request) on
  2 CPUs: 0.83 GB to 6.7 GB, about 1 GB more after each long text and no plateau. On 8 CPUs 1.0 GB to
  2.0 GB. Python's own memory stayed at 83 MB and the count of live tensors constant, so it was native memory.
* **Not the cause** (each tried on the 2-CPU run, none stopped the growth): `MALLOC_ARENA_MAX`,
  `MALLOC_MMAP_THRESHOLD_`/`MALLOC_TRIM_THRESHOLD_` (one good run, then a bad one), `malloc_trim`, jemalloc,
  `MKL_DISABLE_FAST_MM`, `ONEDNN_PRIMITIVE_CACHE_CAPACITY=0`. Run-to-run noise was about 0.5 GB.
* **The watermark was.** With `WATERMARK_ENABLED` off the same 12 requests stayed at 0.88 to 1.0 GB. AudioSeal's
  generator is TorchScript, which compiles and keeps a specialised version for every new input length; the
  pipeline fed it each clip at its own length. Applied to 20 clips of random length on 2 CPUs: 0.59 GB to
  4.9 GB, each call taking 0.2 to 5.2 s. Applied in fixed 4 s windows (the last one padded): flat at 0.85 GB,
  0.2 to 0.6 s per call.

The fix runs the generator on windows of 64,000 samples (a whole number of the detector's 320-sample frames).

| Same speech-like clips, real networks | Old (whole clip) | New (4 s windows) |
|---|---|---|
| Detector probability, 0.5 s to 15 s | 0.99 to 1.00 | 0.99 to 1.00 |
| Tag match, bit accuracy | yes, 1.00 | yes, 1.00 |
| Residual level against the speech | -29 to -36 dB | -29 to -36 dB |
| Step in the residual at a window edge | not applicable | 0.0004 (typical sample step 0.0001) |
| Pipeline, 30 requests on 2 CPUs | 0.83 to 6.7 GB | flat at 1.3 GB, one peak at 2.5 GB |

Limits: detection and level checked on synthetic speech-like clips, not on real clones, and not after MP3 or
resampling beyond what the existing real-network tests cover (they pass); the pipeline run was 2 CPUs only, the
8-CPU rerun was not done; the detector (`detect`, used only by the offline `detect_watermark` tool) still takes
whole clips and was not changed; the 2.5 GB peak for a long text is the figure to size the container for.

### Re-timing the Railway-sized CPUs (S3.5h, 2026-10-25)

S3.5d's table predates the watermark fix (S3.5g), the early stop (S3.5e) and the CPU-scaled limits (S3.5f), so
it was rerun on the service as it now boots: the real pipeline (`run_inference_pipeline`, quality gate on,
default timeouts) pinned with `taskset` to 8, 4, 2 and 1 logical CPUs and the same thread count for torch,
no GPU, warm-up and admission calibration done first (`warmup_inference`, margin 0.8). 4 reference voices,
each asked for four 9-word sentences and one 38-word text (16 short requests and 4 long per size).

| CPUs | 9-word sentence, median (p90) | Real-time factor | 38 words, median | Peak memory | Boot warm-up + timing |
|---|---|---|---|---|---|
| 8 | 5.7 s (6.2) | 2.0 | 10.0 s | 2.0 GB | 18 s |
| 4 | 7.3 s (8.2) | 2.4 | 13.6 s | 2.5 GB | 24 s |
| 2 | 10.2 s (12.4) | 3.5 | 19.2 s | 2.5 GB | 35 s |
| 1 | 11.4 s (12.5) | 3.9 | 21.5 s | 2.6 GB | 37 s |

Against S3.5d: a short sentence is unchanged (5.5, 7.5, 10.8, 11.8 s then), a 38-word text is 25% faster at
2 CPUs (25.6 to 19.2 s) and 23% at 1 CPU (28.0 to 21.5 s), and peak memory no longer grows as threads fall
(was 1.7, 3.2, 4.6, 4.9 GB). Warm-up is the first request's cost moved to boot, so it appears here, not in
the request times.

| Longer texts (warmed up) | 8 CPUs | 4 CPUs | 2 CPUs | 1 CPU |
|---|---|---|---|---|
| 38 words | served, 10 s | served, 14 s | served, 19 s | served, 22 s |
| 60 words | served, 40 s (one retry) | served, 22 s | refused at once | refused at once |
| about 85 words (483 characters) | served, 22 s | refused at once | refused at once | refused at once |
| Three short requests at once | 2 served, 1 queue timeout at 10 s | 2 served, 1 timeout | 2 served, 1 timeout | 1 served, 2 timeouts |

* **No request timed out at a stage limit.** Every long text was either served or refused before it queued;
  the S3.5d failures at 30 s are gone.
* **The gate cost time and a failure.** At 8 CPUs one sentence failed the speech-time check on both attempts
  (14 s spent, no audio) and the 60-word text was truncated once and retried (40 s against about 20 s).
  Reference voices were screened first because an earlier pass with an unscreened voice failed the gate on
  3 of 4 sentences, so the failure rate here belongs to these voices, not to users. A retry doubles the time
  and is still not in the admission estimate.
* **Concurrency is unchanged by the fixes:** one inference at a time, so a second short request waits one
  full request (7 to 11 s at 8 and 4 CPUs, 10 to 20 s below) and a third is turned away after 10 s. At 1 CPU
  the 10 s wait is shorter than one request, so only the first is served.
* **Size the container for about 2.6 GB.** The earlier 4.9 GB figure was the watermark leak.

Limits: a fast desktop CPU (i7-13700HX) with hyperthread pairs standing in for vCPUs, so a Railway vCPU
will be slower; boot timing, which re-fits the limits to the machine, is the safeguard. Four voices, whose
references are synthetic listening-test clips (no real speech was on this machine this session), 16 short and
4 long requests per size, one run of the 60-word, long and concurrency cases. Railway's plan vCPU and memory
limits were still not checked against its documentation or a deployed service.

### Gate retries and the request budget (S3.5j, 2026-10-25)

Admission control (S3.5f) judges one vocoder pass against the 30 s stage limit. A gate retry (S3.4) is another
full synthesis with a fresh stage limit, so it never breaks that limit; it lengthens the request and holds the
single inference slot. S3.5h saw it: a 60-word text on 8 CPUs took 40 s against about 20 s after one retry.
The worst case is 2 attempts x 2 stages x 30 s = 120 s, exactly the web app's request timeout.

Shrinking the word limit to pay for a possible retry would roughly halve it (about 49 to 25 words on 2 CPUs)
to cover an event seen in about 1.4% of short requests, so the limits were kept. Instead the request has a
time budget (`TTS_REQUEST_BUDGET_SECONDS`, 90 s): after a failed attempt, if the time already spent plus
another attempt of the same length would pass it, the attempt is refused at once (the same quality refusal)
rather than retried into a client timeout that discards the audio anyway.

Limits: tested with a stubbed vocoder, not measured on a real CPU; the retry is assumed to cost what the failed
attempt did (a smaller-chunk retry after truncation may differ); how often the budget binds is not measured.

### Does cleaning the reference lower the garbled rate? (S3.5k, 2026-10-26)

Noise in the reference raised the bad rate from about 1% to 22% (S3.5), so the obvious fix is to clean the
recording at upload. Tested before building it: 56 Common Voice speakers (28 women, 28 men, the first
selected by `prepare_cv_corpus --per-group 14` from the female and male downloads), each cloned two ways from
the same 10 to 30 s reference (several of the speaker's clips joined): as recorded, and after spectral-gating
noise reduction (`noisereduce`, stationary, `prop_decrease` 0.8). Six sentences of 8 to 11 words, the same
seeds for both, GPU, the S3.5 gate on, scored by the recogniser (faster-whisper small.en). 672 clips.

| Reference | Clips refused by the gate | Clips with WER 0.34 or worse (of those scored) | Mean WER | Speaker similarity to held-out real speech |
|---|---|---|---|---|
| As recorded | 8 of 336 | 25.3% | 0.263 | 0.717 |
| Noise-reduced | 0 of 336 | 28.6% | 0.343 | 0.690 |

* **Cleaning did not lower the bad rate.** Paired by speaker, it rose 1.9 points (95% bootstrap interval -5.1
  to +8.8; Wilcoxon p = 0.59): 16 speakers improved, 22 got worse, 18 were unchanged.
* **It made the voice less like the speaker.** Similarity fell 0.027 (interval -0.040 to -0.015), lower for
  41 of 56 speakers. The same noise reduction that was meant to help changes what the encoder hears.
* **The refusals went to zero, but not the bad clips.** Counting a refused clip as bad, the raw rate is
  27.7% against 28.6% cleaned: no difference.
* **Women fail more again:** 31.5% against 21.8% (as recorded), as in S3.5b. Cleaning left women at 31.0% and
  took men to 26.2%.
* **Do not read the 18 worst speakers as a rescue.** The 18 speakers who failed on 30% or more as recorded
  averaged 70.0% bad and 55.6% cleaned, but they were picked for being bad on the first run, so part of the
  drop is chance (regression to the mean); the paired result over all 56 is the fair one.

Decision: noise reduction at upload is not built. Limits: one denoiser with one setting (a stronger or learned
one, such as DeepFilterNet, was not tried); a joined 10 to 30 s reference, not the one-clip profile of S3.5b,
so the 25.3% is not comparable with its 19.3%; 56 speakers, one seed; Common Voice only; recogniser labels;
whether the cleaned clone sounds cleaner to a listener was not asked.

### Speech time per chunk of long text (S3.6a, 2026-10-26)

Question: the S3.5 speech-time check only covers texts of 6 to 11 words. Long text is decoded in chunks, so can the
same test be applied to each chunk? What shipped is the plumbing and a measurement: the pipeline now reports where
each chunk sits in the waveform (`ChunkSpan`), the gate measures the worst chunk's speech ratio on its own slice,
and a new reason `chunk_speech_too_long` fires above `TTS_GATE_CHUNK_MAX_SPEECH_RATIO` (default 0: measure and log
only, never refuse). Study: 12 LibriSpeech test-clean speakers (one 10 to 30 s reference each) x 6 punctuated
paragraphs of 45 to 60 words, GPU, real weights, seed 1234 + paragraph, default 150-character chunks: 180 chunks.

| Chunk size | Chunks | Speech ratio against the S3.5 line: mean | 95th percentile | Maximum |
|---|---|---|---|---|
| 6 to 11 words | 24 | 0.83 | 0.98 | 1.19 |
| 12 to 17 words | 48 | 0.84 | 0.98 | 2.26 |
| 18 to 27 words | 108 | 0.77 | 0.97 | 1.34 |

* **Most real chunks are outside the calibrated range.** Chunks ran 11 to 27 words; only 24 of 180 (13%) fall in 6
  to 11, so with the S3.5 range the per-chunk check judges few chunks. Widening the range needs a fitted line.
* **The S3.5 line is loose for longer chunks.** On these clean chunks speech seconds = -0.08 + 0.247 x words (168
  chunks that were not truncated), against -0.50 + 0.339 x words from Common Voice sentences. Extended past 11 words
  the old line would put clean chunks at about 0.8, so a 1.8 limit on it would only fire at about 2.3 times
  the clean fit (at 20 words). A limit set from this line would be too lax to be useful.
* **The one chunk above 1.5 was already refused.** The 2.26 chunk (16 words, 11.1 s of speech) came from a
  decode that hit the frame cap, which the gate's `truncated` reason catches. Without truncated paragraphs
  (12 of 36 had one) the clean maximum against the own fit is 1.54 and the 99th percentile 1.37.

Decision: the per-chunk limit stays off. This measures only the clean side: there are no garbled-chunk labels,
so the share of garbled chunks caught and the false-refusal rate at a chosen limit are **not** measured.

Limits: LibriSpeech readers (cleaner than Common Voice, where the S3.5 fault lives); 12 speakers, one seed; hand
written paragraphs; the 0.247 line is a fit on clean chunks, not a validated model; no recogniser, so nothing says
which chunks were garbled. The next step (S3.6b) needs the Common Voice corpus: synthesize long text, score each
chunk's slice with the recogniser, fit the line on correct chunks, choose a limit at about 0.2% false refusals and
report the catch rate.

### Does the per-chunk speech-time check catch garbled chunks? (S3.6b, 2026-10-26)

Question: S3.6a left the per-chunk limit off because no chunk was labelled garbled. Can a limit on a chunk's speech
time catch the garbled ones without refusing good ones? Data: 48 Common Voice speakers (24 elderly, 24 adult
controls; 24 men, 24 women), each cloned from one joined 10 to 30 s reference, 6 paragraphs x 2 seeds, GPU, default
150-character chunks, real weights: 1,920 chunks. Each chunk's slice of the waveform was transcribed (faster-whisper
small.en) and scored against that chunk's text; a chunk is garbled at WER 0.34 or worse (the S3.5b cut).

| Measure | Result |
|---|---|
| Chunks / words per chunk | 1,920; 3 to 17 words, 25% inside the calibrated 6 to 11 |
| Garbled chunks (WER 0.34 or worse) | 31.8% (elderly 33.6%, adult controls 30.0%) |
| Fit on correct chunks of untruncated paragraphs (n = 1,309) | speech seconds = 0.058 + 0.276 x words |
| Limit at 2% / 1% / 0.5% / 0.2% false refusals | 1.62 / 1.74 / 1.89 / 1.97 times the fit |
| Garbled chunks caught at those limits (588 untruncated) | 19.6% / 13.6% / 9.0% / 7.7% |

* **The check is weak per chunk.** At about 0.2% false refusals it catches 7.7% of garbled chunks. Short chunks make
  the labels noisy (one wrong word in 3 is WER 0.33), so the cut was repeated on chunks of 8 words or more only
  (375 chunks, 95 garbled, 25.3%): 16.8% caught at 0.2% false refusals (limit 1.68), 30.5% at 2%; area under the
  curve 0.74.
* **The per-chunk line is not the S3.5 line.** Correct chunks follow 0.058 + 0.276 x words here (-0.14 + 0.294
  from 8 words), against -0.50 + 0.339 on whole sentences and -0.08 + 0.247 on clean LibriSpeech (S3.6a): three
  different lines, so any limit is only as good as the line behind it.
* **Chunk garbling is common on Common Voice references,** 31.8% of chunks against 11.6% to 19.8% of whole
  6 to 11 word clips in S3.5b. The label is stricter per word at this length and a long text has several chunks to
  fail, so the two rates are not comparable one to one.

Decision: `TTS_GATE_CHUNK_MAX_SPEECH_RATIO` stays 0 (measure only). A limit that costs 0.2% false refusals would
catch 8 to 17% of garbled chunks and, as in S3.5, would not repair what it misses; 2% false refusals for a
20 to 30% catch is not worth a refused request. The speech-time signal is the wrong tool for chunks; a
recogniser pass or a better reference is what reduces the rate (S3.5b: four clips cut garbled output by 40%).

Limits: one seed pair per paragraph; six hand-written paragraphs whose chunks reach only 17 words; one reference
per speaker (not the four-clip profile the product recommends); the recogniser is itself wrong on short slices, and
chunk slices cut at the pause boundary can clip a word; the fit uses only chunks the recogniser passed, which biases
it toward fast, clean speech.

### Does best-of-N reduce garbled speech? (S2.5c, 2026-10-26)

Question: S2.5b found best-of-3 raised similarity by 0.021 on the selecting encoder. The product's visible fault is
garbled output (S3.5b, S3.6b), which similarity does not measure. Does picking among candidates reduce it? Data:
32 Common Voice speakers (16 elderly, 16 adult controls; 16 men, 16 women), one joined 10 to 30 s reference each,
6 hand-written sentences of 9 to 10 words, 3 candidates per sentence from different seeds through the production
pipeline (gate and retries on, `TTS_BEST_OF_N` 1), GPU, scored by the recogniser (faster-whisper small.en); garbled =
WER 0.34 or worse. `python -m backend.evaluate_synthesis --garbled-best-of 3`. 192 sentences, 576 candidates.
Three selectors choose among the same candidates: the first (what N=1 serves), the closest to the profile under
the model's own encoder (what best-of-N serves today), and the lowest WER (an upper bound: it reads the recogniser
that also scores it).

| Selector | Garbled sentences | Change against first (paired by speaker, 95% interval) |
|---|---|---|
| First candidate | 18.2% | none |
| Closest voice (today's best-of-3) | 19.3% | +1.0 points (-1.6 to +4.7) |
| Lowest WER (upper bound) | 12.5% | -5.7 points (-9.9 to -2.1) |
| All three candidates garbled | 12.5% | the floor for any selector |

* **Today's selection does not help.** Choosing by voice similarity left the garbled rate where it was (18.2% to
  19.3%, interval spans zero). Similarity and garbling are not the same property, so best-of-3 as built costs about
  2.9 times the compute without lowering the fault users hear.
* **Even a perfect selector removes only a third.** The lowest-WER pick reaches 12.5%, which is exactly the share
  of sentences where all three candidates failed. The remaining garbling belongs to the speaker or the reference
  (some voices fail on every seed), not to the seed, so more candidates cannot fix it.
* **Three candidates were refused outright** by the gate after its retries (counted as garbled, never selected).
* **Elderly and adult controls did not differ meaningfully** (first-candidate 15.6% against 20.8%).
* **ECAPA similarity was not measured.** `speechbrain` is not in the project environment (the S0.1f run used a
  separate torch 2.6 environment) and was not installed here, so the independent-encoder half of S2.5's open item
  is still open. The garbled-rate question did not need it.

Decision: `TTS_BEST_OF_N` stays 1. A WER-aware selector (S2.5d) could remove up to 5.7 points of 18.2 (a third), but
only at 3 times the synthesis cost plus a recogniser at serve time, and the oracle number is optimistic. The cheaper
lever stays the one S3.5b measured: more reference clips cut the garbled rate by 8.2 points at no serving cost.

Limits: 32 speakers, one seed set, six sentences of 9 to 10 words; one reference clip per speaker, not the multi-clip
profile the product recommends; the recogniser is noisy and the oracle shares it with the score; the study seeds
candidates directly, which is statistically the same as the production extras but not byte-identical to them.

## Next measurements, in order

1. ~~Multi-sentence and number-heavy stimuli with word error rate~~ (done, section above).
2. ~~An emotion classifier~~ (done, S0.3 above), ~~a predicted-naturalness model and RTF~~ (done, S0.1e above), ~~an **independent** speaker encoder~~ (done, S0.1f above), and a first blind listening test of the S1 pause lengths (pack built and browser-checked, S0.7; **no listener has heard it**).
3. ~~A positive control for the question metric (natural questions)~~ (done, S0.3b above; a punctuated corpus would tighten it).
4. ~~Elderly speech from a source with verified licence terms~~ (done for adult males and females, section above); child speech remains open (children out of scope, Q4). The F0 tracker was checked, the metric guarded and both studies re-scored (S0.2e/S0.2f); the two elderly-women outliers (`109292d3b481`, `062a915b1870`) were inspected (S0.2g), excluded by the S0.2h range-agreement check, and the women's study re-scored (elderly F0 error 2.94 semitones against 1.94 for the control).
