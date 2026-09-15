"""SHA256 checksum verification for SV2TTS checkpoint files.

Real trained SV2TTS weights are too large and too sensitive a supply-chain
surface to check into this repository (HARDENING_PLAN.md findings C2 and
C3), so they are provisioned separately by an operator. This module pins the
manifest of trusted hashes (`backend/weights_manifest.json`, checked into
git — hashes only, never the weights themselves) and is the single place
both the running app (`backend.services.tts_pipeline.load_models`) and the
provisioning script (`backend.download_weights`) verify a checkpoint's
integrity before it is ever handed to `torch.load`. A corrupted download or
a tampered file is rejected here, before any deserialization is attempted.
"""

import hashlib
import json
import os

MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "weights_manifest.json"
)


def load_manifest() -> dict:
    """Load the pinned checksum manifest.

    Returns:
        The parsed manifest dict (see `backend/weights_manifest.json`).

    Raises:
        RuntimeError: If the manifest is missing or malformed. Unlike a
            missing checkpoint (an expected, documented provisioning step),
            a missing manifest means the deployment itself is broken — the
            file ships with the repository.
    """
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Could not read checksum manifest at '{MANIFEST_PATH}': {exc}. "
            "This file ships with the repository — a missing or corrupt copy "
            "indicates a broken deployment, not just missing model weights."
        ) from exc


def verify_checksum(path: str, filename: str, manifest: dict) -> None:
    """Verify a checkpoint file's SHA256 against the pinned manifest.

    Args:
        path: Filesystem path to the checkpoint to verify.
        filename: Logical name to look up in the manifest (e.g.
            ``"synthesizer.pt"``) — independent of ``path``'s actual
            location, so a custom ``WEIGHTS_DIR`` still verifies correctly.
        manifest: The dict returned by ``load_manifest()``.

    Raises:
        RuntimeError: If there is no manifest entry for ``filename``, or its
            computed SHA256 does not match the pinned value. In both cases
            the caller must not proceed to load the file.
    """
    entry = manifest.get("files", {}).get(filename)
    if entry is None:
        raise RuntimeError(
            f"No checksum entry for '{filename}' in {MANIFEST_PATH}. "
            "Refusing to load an unverified checkpoint."
        )

    expected = entry["sha256"]
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()

    if actual != expected:
        raise RuntimeError(
            f"Checksum mismatch for '{filename}': expected {expected}, got "
            f"{actual}. The checkpoint may be corrupted or tampered with — "
            "refusing to load it. Re-download from the source recorded in "
            f"{MANIFEST_PATH} ('source' field)."
        )
