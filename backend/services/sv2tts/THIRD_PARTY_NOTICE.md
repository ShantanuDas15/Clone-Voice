# Third-Party Notice — Vendored SV2TTS Model Code

The code under `backend/services/sv2tts/` is vendored, with minimal modification, from:

- **Repository:** https://github.com/CorentinJ/Real-Time-Voice-Cloning
- **Commit pinned during vendoring:** `890f3a03187195b9829db2079b75c2ba2ab0405c`
- **License:** MIT (full text below)

Pretrained checkpoints (`synthesizer.pt`, `vocoder.pt`) are downloaded separately from
https://huggingface.co/CorentinJ/SV2TTS (same MIT license) and verified against
`backend/weights_manifest.json` before use — see `backend/download_weights.py` and
`backend/services/tts_pipeline.py`. The weights themselves are never committed to this
repository (HARDENING_PLAN.md findings C2, C3).

## What was vendored (inference-only subset)

Only the modules needed to *load a trained checkpoint and run inference* were copied — no
training loops, data loaders, or preprocessing scripts:

- `synthesizer/hparams.py`, `synthesizer/models/tacotron.py`
- `synthesizer/utils/{symbols,text,cleaners,numbers}.py`
- `vocoder/hparams.py`, `vocoder/models/fatchord_version.py`, `vocoder/distribution.py`, `vocoder/display.py`, `vocoder/audio.py`

Files with no cross-package imports were copied byte-for-byte. Files that import sibling
modules (e.g. `from synthesizer.utils.symbols import symbols`) had only their import paths
rewritten to this package's location (e.g.
`from backend.services.sv2tts.synthesizer.utils.symbols import symbols`) — verified via `diff`
against the upstream source to confirm no other line changed at vendoring time. `black`/`isort`
were then run across the whole repository, this package included, per CLAUDE.md §3.2 — a
style-only pass (quoting, wrapping, import ordering) with no logic change, same as every other
file here.

## Deviations from upstream

**`vocoder/models/fatchord_version.py` — device placement (HARDENING_PLAN.md finding H1).**
Upstream's `WaveRNN.forward()`, `.generate()`, `.pad_tensor()`, and `.fold_with_overlap()` each
branched on the process-global `torch.cuda.is_available()` to decide whether to allocate
tensors with `.cuda()` or `.cpu()` — never checking which device the model's own parameters
were actually placed on. Reproduced during this hardening pass: a `WaveRNN` instance explicitly
loaded onto `cpu` in a CUDA-capable process (this dev machine has a GPU; `settings.DEVICE`
defaults to `"cpu"`) still allocated CUDA tensors internally and crashed with
`RuntimeError: Input type (torch.cuda.FloatTensor) and weight type (torch.FloatTensor) should
be the same`. Patched every occurrence to derive the device from the model's own parameters
(`next(self.parameters()).device`) or from the already-correctly-placed input tensor
(`x.device`), matching the pattern upstream's own `Tacotron.forward()` already uses correctly.
Each patch site is marked `# PATCHED` in the file with a comment pointing back to this notice.
No other behavior was changed.

**`vocoder/models/fatchord_version.py` — deprecated NumPy API.** `UpsampleNetwork.__init__`
used `np.cumproduct`, deprecated since NumPy 1.25 and removed entirely in NumPy 2.0. Replaced
with `np.cumprod`, its exact non-deprecated equivalent (same function, no behavior change) —
this only prevents a future NumPy upgrade from breaking model construction.

## License

```
MIT License

Modified & original work Copyright (c) 2019 Corentin Jemine (https://github.com/CorentinJ)
Original work Copyright (c) 2018 Rayhane Mama (https://github.com/Rayhane-mamah)
Original work Copyright (c) 2019 fatchord (https://github.com/fatchord)
Original work Copyright (c) 2015 braindead (https://github.com/braindead)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
