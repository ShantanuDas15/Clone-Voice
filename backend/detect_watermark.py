"""Check whether an audio file carries this service's inaudible watermark (S7.2b).

    python -m backend.detect_watermark clip.wav [--search-alignment]

For abuse review: prints a JSON verdict (probability, whether the 12-bit service tag matches, and which
engine's code the message carries). Exit status 0 means a watermark was found, 1 means none, 2 means the
file could not be read. ``--search-alignment`` also finds the watermark in audio that was trimmed at an
arbitrary sample, at the cost of several seconds per clip. A change of speed or pitch, or heavy noise,
can defeat detection, so "not found" is not proof the clip did not come from this service.
"""

import argparse
import json
import os
import sys
from typing import List, Optional

import numpy as np
import soundfile as sf

from backend.services import watermark


def _read(path: str) -> tuple:
    """Read a file as mono float32 at its own rate (wav, flac, ogg, and mp3 with a recent libsndfile)."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"no such file: {path}")
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    return np.mean(audio, axis=1), rate


def main(argv: Optional[List[str]] = None) -> int:
    """Run the detector on one file and print the verdict."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("file")
    parser.add_argument("--search-alignment", action="store_true")
    args = parser.parse_args(argv)
    try:
        audio, rate = _read(args.file)
        detection = watermark.get_watermarker().detect(
            audio, rate, args.search_alignment
        )
    except Exception as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "watermarked": detection.watermarked,
                "probability": round(detection.probability, 4),
                "tag_matches": detection.tag_matches,
                "engine": detection.engine,
            }
        )
    )
    return 0 if detection.watermarked else 1


if __name__ == "__main__":
    sys.exit(main())
