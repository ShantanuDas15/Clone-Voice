"""Blind listening-test kit (SPEECH_QUALITY_PLAN.md S0.5): the test that decides release.

    python -m backend.listening_test build --system sv2tts=<dir> --system chatterbox=<dir> \\
        --out <test dir> --key <key.json> [--seed 1] [--max-per-pair 20] [--anchors 4]
    python -m backend.listening_test analyze --key <key.json> --responses r1.json r2.json ...

``build`` pairs the audio of two or more systems, written as ``<dir>/<speaker>/<i>.wav`` (the layout
``score_engine_outputs`` reads). The first ``--system`` is the baseline; every other system is
compared against it on the clips both made. Each trial's two clips are levelled to the same
loudness (so louder is not mistaken for better), shown in random left/right order under neutral
names, and written to a static page that works from disk or any file host: give listeners the
``--out`` folder only. The answer key stays in ``--key`` and must not be shared.

Anchor trials (the baseline's own clip against a deliberately damaged copy of it) check that a
listener is paying attention; ``analyze`` leaves out listeners who prefer the damaged copy too
often. Results are a preference share per comparison with a Wilson interval and an exact binomial
p-value. Evaluation only: numpy, scipy, soundfile; never imported by the app.
"""

import argparse
import html
import json
import math
import random
import sys
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

from backend.services.audio_polish import integrated_loudness

TARGET_LUFS = -23.0
PEAK_LIMIT = 0.97
ANCHOR_LOWPASS_HZ = 3000.0
ANCHOR_SNR_DB = 5.0
DEFAULT_QUESTION = "Which recording sounds more natural and human?"
CHOICES = ("a", "b", "none")


# --- audio ---------------------------------------------------------------------------


def match_loudness(
    waveform: np.ndarray, sample_rate: int, target: float = TARGET_LUFS
) -> np.ndarray:
    """The waveform scaled to ``target`` LUFS, held below ``PEAK_LIMIT`` (never clipped)."""
    level = integrated_loudness(waveform, sample_rate)
    peak = float(np.max(np.abs(waveform))) if waveform.size else 0.0
    if level is None or peak == 0.0:
        return waveform.astype(np.float32)
    gain = 10.0 ** ((target - level) / 20.0)
    gain = min(gain, PEAK_LIMIT / peak)
    return (waveform * gain).astype(np.float32)


def degrade(waveform: np.ndarray, sample_rate: int, seed: int) -> np.ndarray:
    """A deliberately worse copy: band-limited and noisy, as an attention check."""
    nyquist = sample_rate / 2.0
    cutoff = min(ANCHOR_LOWPASS_HZ, nyquist * 0.9)
    sos = butter(4, cutoff / nyquist, output="sos")
    filtered = sosfilt(sos, waveform.astype(np.float64))
    power = float(np.mean(filtered**2)) or 1e-12
    noise_power = power / (10.0 ** (ANCHOR_SNR_DB / 10.0))
    noise = np.random.default_rng(seed).normal(
        0.0, math.sqrt(noise_power), len(filtered)
    )
    return (filtered + noise).astype(np.float32)


# --- building ------------------------------------------------------------------------


def list_clips(directory: Path) -> Dict[str, Path]:
    """Every ``.wav`` under ``directory``, keyed by its path relative to it."""
    return {
        p.relative_to(directory).as_posix(): p for p in sorted(directory.rglob("*.wav"))
    }


def plan_trials(
    systems: Mapping[str, Dict[str, Path]],
    seed: int,
    max_per_pair: Optional[int] = None,
    anchors: int = 0,
) -> List[dict]:
    """The trial list: baseline vs each other system on shared clips, plus anchors.

    ``systems`` maps a name to its clips; the first entry is the baseline. Which side holds which
    system is drawn once per trial from ``seed``. Trials come back in a seeded random order with
    ids ``t001``...; the page shuffles again per listener.
    """
    names = list(systems)
    if len(names) < 2:
        raise ValueError("a listening test needs at least two systems")
    rng = random.Random(seed)
    baseline = names[0]
    trials: List[dict] = []
    for other in names[1:]:
        shared = sorted(set(systems[baseline]) & set(systems[other]))
        if not shared:
            raise ValueError(f"{baseline} and {other} have no clip in common")
        if max_per_pair is not None and len(shared) > max_per_pair:
            shared = sorted(rng.sample(shared, max_per_pair))
        for item in shared:
            sides = [baseline, other]
            rng.shuffle(sides)
            trials.append({"kind": "pair", "a": sides[0], "b": sides[1], "item": item})
    pool = sorted(systems[baseline])
    for item in rng.sample(pool, min(anchors, len(pool))):
        sides = [baseline, "degraded"]
        rng.shuffle(sides)
        trials.append({"kind": "anchor", "a": sides[0], "b": sides[1], "item": item})
    rng.shuffle(trials)
    for number, trial in enumerate(trials, start=1):
        trial["id"] = f"t{number:03d}"
    return trials


def _read_mono(path: Path) -> Tuple[np.ndarray, int]:
    """A clip as mono float32 and its sample rate."""
    data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    return data.mean(axis=1), rate


def write_trial_audio(
    trial: dict, systems: Mapping[str, Dict[str, Path]], out_dir: Path, seed: int
) -> None:
    """Write ``<id>_a.wav`` and ``<id>_b.wav``, levelled to the same loudness."""
    baseline = next(iter(systems))
    for side in ("a", "b"):
        name = trial[side]
        if name == "degraded":
            wave, rate = _read_mono(systems[baseline][trial["item"]])
            wave = degrade(wave, rate, seed + int(trial["id"][1:]))
        else:
            wave, rate = _read_mono(systems[name][trial["item"]])
        sf.write(
            str(out_dir / f"{trial['id']}_{side}.wav"),
            match_loudness(wave, rate),
            rate,
            subtype="PCM_16",
        )


def render_page(trial_ids: Sequence[str], question: str, title: str) -> str:
    """The listener page: one self-contained HTML file, no external resources, no key."""
    ids = json.dumps(list(trial_ids))
    return (
        _PAGE.replace("__TITLE__", html.escape(title))
        .replace("__QUESTION__", html.escape(question))
        .replace("__IDS__", ids)
    )


def build(
    systems: Mapping[str, Path],
    out_dir: Path,
    key_path: Path,
    seed: int = 1,
    max_per_pair: Optional[int] = None,
    anchors: int = 0,
    question: str = DEFAULT_QUESTION,
) -> dict:
    """Write the test folder and the private key; return the key."""
    clips = {name: list_clips(Path(path)) for name, path in systems.items()}
    trials = plan_trials(clips, seed, max_per_pair, anchors)
    audio_dir = out_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for trial in trials:
        write_trial_audio(trial, clips, audio_dir, seed)
    (out_dir / "index.html").write_text(
        render_page([t["id"] for t in trials], question, "Listening test"),
        encoding="utf-8",
    )
    key = {"seed": seed, "question": question, "trials": trials}
    key_path.write_text(json.dumps(key, indent=2), encoding="utf-8")
    return key


# --- analysis ------------------------------------------------------------------------


def wilson(wins: int, total: int, z: float = 1.96) -> Tuple[float, float]:
    """The Wilson score interval for a proportion; (0, 1) when there are no trials."""
    if total == 0:
        return 0.0, 1.0
    p = wins / total
    denom = 1.0 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def binomial_two_sided(wins: int, total: int) -> float:
    """Exact two-sided p-value for ``wins`` of ``total`` under a fair coin."""
    if total == 0:
        return 1.0
    tail = sum(math.comb(total, k) for k in range(max(wins, total - wins), total + 1))
    return min(1.0, 2.0 * tail / 2**total)


def _load_responses(paths: Sequence[Path], valid_ids: set) -> Dict[str, Dict[str, str]]:
    """Each listener's ``{trial id: choice}``; a bad file or repeated listener is an error."""
    listeners: Dict[str, Dict[str, str]] = {}
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        listener = str(data.get("listener") or Path(path).stem)
        if listener in listeners:
            raise ValueError(f"listener {listener!r} appears twice")
        answers: Dict[str, str] = {}
        for entry in data.get("answers", []):
            trial, choice = entry.get("trial"), entry.get("choice")
            if trial not in valid_ids:
                raise ValueError(f"{path}: unknown trial {trial!r}")
            if choice not in CHOICES:
                raise ValueError(f"{path}: bad choice {choice!r} for {trial}")
            answers[trial] = choice
        listeners[listener] = answers
    return listeners


def analyze(
    key: Mapping[str, object],
    response_paths: Sequence[Path],
    min_anchor_accuracy: float = 0.75,
) -> dict:
    """Preference per comparison, after leaving out listeners who fail the anchors."""
    trials = {t["id"]: t for t in key["trials"]}  # type: ignore[index]
    listeners = _load_responses(response_paths, set(trials))
    kept: Dict[str, Dict[str, str]] = {}
    excluded: Dict[str, float] = {}
    for listener, answers in listeners.items():
        scored = [
            (trials[i], c) for i, c in answers.items() if trials[i]["kind"] == "anchor"
        ]
        if len(scored) >= 2:
            right = sum(
                1
                for t, c in scored
                if c != "none" and t[c] != "degraded"  # picked the undamaged copy
            )
            accuracy = right / len(scored)
            if accuracy < min_anchor_accuracy:
                excluded[listener] = accuracy
                continue
        kept[listener] = answers

    tallies: Dict[Tuple[str, str], Dict[str, int]] = {}
    for answers in kept.values():
        for trial_id, choice in answers.items():
            trial = trials[trial_id]
            if trial["kind"] != "pair":
                continue
            pair = tuple(sorted((trial["a"], trial["b"])))
            tally = tallies.setdefault(pair, {"none": 0, pair[0]: 0, pair[1]: 0})
            tally["none" if choice == "none" else trial[choice]] += 1

    comparisons = []
    for (first, second), tally in sorted(tallies.items()):
        decided = tally[first] + tally[second]
        low, high = wilson(tally[second], decided)
        comparisons.append(
            {
                "systems": [first, second],
                "wins": {first: tally[first], second: tally[second]},
                "no_preference": tally["none"],
                "share_second": tally[second] / decided if decided else None,
                "ci95_second": [low, high],
                "p_value": binomial_two_sided(tally[second], decided),
            }
        )
    return {
        "listeners": len(listeners),
        "kept": len(kept),
        "excluded_for_anchors": excluded,
        "comparisons": comparisons,
    }


# --- command line --------------------------------------------------------------------


def _parse_systems(values: Sequence[str]) -> Dict[str, Path]:
    """``name=dir`` pairs, in order (the first is the baseline)."""
    systems: Dict[str, Path] = {}
    for value in values:
        name, sep, path = value.partition("=")
        if not sep or not name or not path or name == "degraded" or name in systems:
            raise SystemExit(f"bad --system {value!r}: use a unique name=dir")
        systems[name] = Path(path)
    return systems


def main(argv: Optional[List[str]] = None) -> int:
    """Build a listening test or analyse its responses."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="make the test folder and the answer key")
    b.add_argument("--system", action="append", required=True, metavar="NAME=DIR")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--key", type=Path, required=True)
    b.add_argument("--seed", type=int, default=1)
    b.add_argument("--max-per-pair", type=int)
    b.add_argument("--anchors", type=int, default=4)
    b.add_argument("--question", default=DEFAULT_QUESTION)
    a = sub.add_parser("analyze", help="score listeners' response files")
    a.add_argument("--key", type=Path, required=True)
    a.add_argument("--responses", type=Path, nargs="+", required=True)
    a.add_argument("--min-anchor-accuracy", type=float, default=0.75)
    a.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    if args.command == "build":
        if args.out.resolve() in args.key.resolve().parents:
            raise SystemExit("keep --key outside the --out folder you will share")
        key = build(
            _parse_systems(args.system),
            args.out,
            args.key,
            args.seed,
            args.max_per_pair,
            args.anchors,
            args.question,
        )
        print(f"{len(key['trials'])} trials in {args.out}; key at {args.key}")
        return 0

    key = json.loads(args.key.read_text(encoding="utf-8"))
    report = analyze(key, args.responses, args.min_anchor_accuracy)
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
body{font:16px/1.5 system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem}
.clip{margin:1rem 0}.row{display:flex;gap:1rem;flex-wrap:wrap;margin:1rem 0}
button{font:inherit;padding:.5rem 1rem}
</style></head><body>
<h1>__TITLE__</h1>
<p>Use headphones in a quiet room. Play both recordings as often as you like, then choose.
There are no right answers except your own impression.</p>
<div id="start"><label>Your name or code <input id="who"></label>
<button id="go">Start</button></div>
<div id="test" hidden>
<p id="progress"></p><h2>__QUESTION__</h2>
<div class="clip">A <audio id="a" controls preload="auto"></audio></div>
<div class="clip">B <audio id="b" controls preload="auto"></audio></div>
<div class="row"><button data-c="a">A is better</button>
<button data-c="b">B is better</button>
<button data-c="none">No difference</button></div></div>
<div id="done" hidden><p>Thank you. Save your answers and send the file back.</p>
<button id="save">Save answers</button></div>
<script>
const ids=__IDS__;let order=[],pos=0,answers=[],who="";
function shuffle(x){for(let i=x.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[x[i],x[j]]=[x[j],x[i]];}return x;}
function show(){if(pos>=order.length){document.getElementById("test").hidden=true;
document.getElementById("done").hidden=false;return;}
const id=order[pos];document.getElementById("a").src="audio/"+id+"_a.wav";
document.getElementById("b").src="audio/"+id+"_b.wav";
document.getElementById("progress").textContent="Pair "+(pos+1)+" of "+order.length;}
document.getElementById("go").onclick=()=>{who=document.getElementById("who").value.trim();
if(!who)return;order=shuffle(ids.slice());document.getElementById("start").hidden=true;
document.getElementById("test").hidden=false;show();};
document.querySelectorAll("[data-c]").forEach(b=>b.onclick=()=>{
answers.push({trial:order[pos],choice:b.dataset.c});pos++;show();});
document.getElementById("save").onclick=()=>{
const blob=new Blob([JSON.stringify({listener:who,answers:answers},null,1)],{type:"application/json"});
const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=who+".json";a.click();};
</script></body></html>
"""

if __name__ == "__main__":
    sys.exit(main())
