"""An inaudible watermark on every synthesized waveform (SPEECH_QUALITY_PLAN.md S7.2b).

WAV metadata (title, software, comment) marks a file as synthetic, but any re-encode strips it. This
adds a watermark in the audio itself, made by Meta's AudioSeal (MIT code and weights): a generator
network adds a very quiet residual (about 25 dB below the speech) that a detector network finds again
after MP3 compression, resampling and moderate noise. It carries a 16-bit message: a 12-bit service
tag and a 4-bit code for the engine that spoke, so an abuse review can tell what produced a clip.

What it does not survive (measured during development; the figures are not recorded in the study): a change of speed or pitch, heavy noise
(15 dB), or a large gain cut. Trimming at an arbitrary sample offset defeats the plain detector, because it
depends on a 320-sample frame grid; ``detect(..., search_alignment=True)`` tries every alignment and
recovers it. This is a provenance signal for investigators, not a lock.

The model runs at 16 kHz. For other rates the residual is made on a 16 kHz copy and then resampled and
added to the original, so the output keeps its own bandwidth.
"""

import logging
import math
import os
import threading
import warnings
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

import numpy as np
from scipy.signal import resample_poly

from backend.core.config import settings
from backend.services.sv2tts.checksum import load_manifest, verify_checksum

# audioseal JIT-compiles two modules with torch.compile unless told not to, which needs a C++
# toolchain at run time. Must be set before audioseal is imported.
os.environ.setdefault("NO_TORCH_COMPILE", "1")

logger = logging.getLogger(__name__)

MODEL_RATE = 16000
NBITS = 16
TAG_BITS = 12
ENGINE_BITS = 4
# AudioSeal's detector works on a 320-sample frame grid (20 ms at 16 kHz).
FRAME = 320
# The generator is TorchScript: it specialises on, and keeps, a compiled version for every new input
# length. Fed whole clips of every length a request can have, memory grew without bound (0.6 GB to
# 4.9 GB over 20 clips on 2 CPUs) and each call took up to 5 s. It is therefore run on windows of this
# one length (a multiple of FRAME, so the detector's frame grid is unchanged), the last one padded.
WINDOW_SAMPLES = 4 * MODEL_RATE
SUBDIR = "audioseal"
GENERATOR_FILE = "generator_base.pth"
DETECTOR_FILE = "detector_base.pth"
# Names in weights_manifest.json (the files live in <WEIGHTS_DIR>/audioseal/).
MANIFEST_KEYS = {
    GENERATOR_FILE: "audioseal/generator_base.pth",
    DETECTOR_FILE: "audioseal/detector_base.pth",
}
HF_REPO_ID = "facebook/audioseal"
# A clip at or above this detector probability is called watermarked. Measured: no unwatermarked
# clip scored above 0.13 even after searching all 320 alignments; watermarked clips score about 1.
DETECT_THRESHOLD = 0.5
# Engine code in the message's low 4 bits. 0 means unknown.
ENGINE_CODES = {
    "sv2tts": 1,
    "chatterbox": 2,
    "chatterbox_turbo": 3,
    "chatterbox_nano": 4,
}
# After an alignment search, offsets within this many samples of each other that read the same tag
# are taken to be one alignment. A search needs a clip of at least this many samples (80 ms).
CLUSTER_RADIUS = 3
SEARCH_MIN_SAMPLES = 4 * FRAME
# Keep samples inside full scale after the residual is added.
PEAK_LIMIT = 0.999


@dataclass(frozen=True)
class Detection:
    """What the detector found in a clip."""

    probability: float
    watermarked: bool
    tag_matches: bool
    engine: Optional[str]
    bit_accuracy_vs_expected_tag: float


def message_bits(tag: int, engine: Optional[str]) -> np.ndarray:
    """The 16-bit message: the 12-bit tag, then the 4-bit engine code (most significant first)."""
    if not 0 <= tag < 2**TAG_BITS:
        raise ValueError("the watermark tag must fit in 12 bits")
    code = ENGINE_CODES.get(engine or "", 0)
    value = (tag << ENGINE_BITS) | code
    return np.array(
        [(value >> (NBITS - 1 - i)) & 1 for i in range(NBITS)], dtype=np.int32
    )


def _resampled(y: np.ndarray, source: int, target: int) -> np.ndarray:
    """Resample ``y`` from ``source`` to ``target`` Hz (a rational ratio)."""
    if source == target:
        return y
    g = math.gcd(source, target)
    return resample_poly(y, target // g, source // g).astype(np.float32)


def _fit(y: np.ndarray, length: int) -> np.ndarray:
    """Trim or zero-pad ``y`` to exactly ``length`` samples."""
    if len(y) >= length:
        return y[:length]
    return np.pad(y, (0, length - len(y)))


class Watermarker:
    """Adds and detects the watermark with a generator and a detector network."""

    def __init__(self, generator: Any, detector: Any, tag: int) -> None:
        """Wrap loaded networks (anything with AudioSeal's ``get_watermark``/``detect_watermark``)."""
        self.generator = generator
        self.detector = detector
        self.tag = tag
        self._lock = threading.Lock()

    @classmethod
    def from_weights(cls, weights_dir: str, tag: int) -> "Watermarker":
        """Load both networks from checksum-verified files; never downloads anything."""
        manifest = load_manifest()
        folder = os.path.join(weights_dir, SUBDIR)
        paths = {}
        for name, key in MANIFEST_KEYS.items():
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                raise RuntimeError(
                    f"watermark weights missing: {path} "
                    "(run `python -m backend.download_weights --fetch`)"
                )
            verify_checksum(path, key, manifest)
            paths[name] = path
        with warnings.catch_warnings():
            # audioseal still uses two APIs that torch has deprecated; they are not ours to fix.
            warnings.filterwarnings(
                "ignore", message=".*weight_norm.*", category=FutureWarning
            )
            warnings.filterwarnings(
                "ignore", message=".*torch.jit.script.*", category=DeprecationWarning
            )
            from audioseal import AudioSeal

            generator = AudioSeal.load_generator(
                paths[GENERATOR_FILE], nbits=NBITS
            ).eval()
            detector = AudioSeal.load_detector(paths[DETECTOR_FILE], nbits=NBITS).eval()
        return cls(generator, detector, tag)

    def apply(
        self, waveform: np.ndarray, sample_rate: int, engine: Optional[str]
    ) -> np.ndarray:
        """Return ``waveform`` with the watermark added, the same length and rate.

        Raises:
            ValueError: If the waveform is not a non-empty, finite 1-D array.
        """
        import torch

        if (
            waveform.ndim != 1
            or waveform.size == 0
            or not np.all(np.isfinite(waveform))
        ):
            raise ValueError(
                "only a non-empty, finite mono waveform can be watermarked"
            )
        y = waveform.astype(np.float32)
        low = _resampled(y, sample_rate, MODEL_RATE)
        message = torch.from_numpy(message_bits(self.tag, engine))[None]
        pieces = []
        with self._lock, torch.no_grad():
            for start in range(0, len(low), WINDOW_SAMPLES):
                part = low[start : start + WINDOW_SAMPLES]
                kept = len(part)
                if kept < WINDOW_SAMPLES:
                    part = np.pad(part, (0, WINDOW_SAMPLES - kept))
                x = torch.from_numpy(part)[None, None]
                piece = self.generator.get_watermark(x, MODEL_RATE, message=message)
                pieces.append(piece[0, 0].numpy()[:kept])
        residual = np.concatenate(pieces)
        residual = _fit(_resampled(residual, MODEL_RATE, sample_rate), len(y))
        marked = y + residual
        peak = float(np.max(np.abs(marked)))
        if peak > PEAK_LIMIT:
            marked = marked * (PEAK_LIMIT / peak)
        return marked.astype(np.float32)

    def _probabilities(self, y16: np.ndarray, offsets: list) -> tuple:
        """Detector probability and message bits at each starting offset of a 16 kHz clip."""
        import torch

        length = len(y16) - max(offsets)
        batch = torch.stack([torch.from_numpy(y16[o : o + length]) for o in offsets])[
            :, None
        ]
        with self._lock, torch.no_grad():
            probability, message = self.detector.detect_watermark(batch, MODEL_RATE)
        return np.atleast_1d(np.asarray(probability, dtype=np.float64)), message.numpy()

    def detect(
        self, waveform: np.ndarray, sample_rate: int, search_alignment: bool = False
    ) -> Detection:
        """Look for the watermark in a clip.

        ``search_alignment`` tries all 320 start offsets: slow (seconds per clip on a CPU) but it
        finds a watermark in audio that was trimmed at an arbitrary sample. The detector's
        probability saturates at 1.0 across many wrong offsets, and the message it reads is only
        correct in a tight cluster of offsets around the true alignment, so after a search the
        message is read from offsets that are both confidently watermarked and carry this
        service's exact 12-bit tag (a random offset matches it by chance about 1 time in 4096),
        taking the densest cluster of such offsets.
        """
        if waveform.ndim != 1 or waveform.size < FRAME * 2:
            raise ValueError(
                "need a mono clip of at least 40 ms to look for a watermark"
            )
        y16 = _resampled(waveform.astype(np.float32), sample_rate, MODEL_RATE)
        searching = search_alignment and len(y16) >= SEARCH_MIN_SAMPLES
        offsets = list(range(FRAME)) if searching else [0]
        probability, message = self._probabilities(y16, offsets)
        bits = (message > 0.5).astype(np.int32)
        expected = message_bits(self.tag, None)[:TAG_BITS]
        best = int(np.argmax(probability))
        candidates = [
            i
            for i in range(len(offsets))
            if probability[i] > DETECT_THRESHOLD
            and np.array_equal(bits[i, :TAG_BITS], expected)
        ]
        engine: Optional[str] = None
        if candidates:
            # The true alignment shows as a run of neighbouring offsets that all read the tag.
            def support(i: int) -> int:
                return sum(
                    1
                    for j in candidates
                    if abs(offsets[j] - offsets[i]) <= CLUSTER_RADIUS
                )

            top = max(support(i) for i in candidates)
            cluster = [i for i in candidates if support(i) == top]
            codes = [
                int("".join(str(int(b)) for b in bits[i, TAG_BITS:]), 2)
                for i in cluster
            ]
            code = max(set(codes), key=codes.count)
            engine = next((n for n, c in ENGINE_CODES.items() if c == code), None)
            read = candidates[0] if len(cluster) == 0 else cluster[0]
        else:
            read = best
        return Detection(
            probability=float(probability[best]),
            watermarked=float(probability[best]) > DETECT_THRESHOLD,
            tag_matches=bool(candidates),
            engine=engine,
            bit_accuracy_vs_expected_tag=float(
                np.mean(bits[read, :TAG_BITS] == expected)
            ),
        )


@lru_cache(maxsize=1)
def get_watermarker() -> Watermarker:
    """The process-wide watermarker, loaded on first use from ``<WEIGHTS_DIR>/audioseal``."""
    return Watermarker.from_weights(settings.WEIGHTS_DIR, settings.WATERMARK_TAG)


def watermark_status() -> dict:
    """Whether the watermark is on and its networks loaded, for the readiness payload."""
    if not settings.WATERMARK_ENABLED:
        return {"enabled": False, "loaded": False}
    try:
        get_watermarker()
    except Exception:
        logger.exception("The watermark networks could not be loaded")
        return {"enabled": True, "loaded": False}
    return {"enabled": True, "loaded": True}
