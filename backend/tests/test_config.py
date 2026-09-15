"""Tests for configuration cleanup (Hardening Phase 4.2)."""

import importlib

from backend.core.config import BASE_DIR, Settings, settings


def test_weights_dir_defaults_to_backend_weights_directory() -> None:
    """`WEIGHTS_DIR` defaults to `backend/weights` when no env override is set."""
    assert settings.WEIGHTS_DIR == str(BASE_DIR / "weights")


def test_weights_dir_is_configurable_via_environment(monkeypatch, tmp_path) -> None:
    """Setting the `WEIGHTS_DIR` env var overrides the default checkpoint path."""
    custom_dir = str(tmp_path / "custom-weights")
    monkeypatch.setenv("WEIGHTS_DIR", custom_dir)
    monkeypatch.setenv("DATABASE_URL", settings.DATABASE_URL)
    monkeypatch.setenv("JWT_SECRET_KEY", settings.JWT_SECRET_KEY)

    overridden_settings = Settings()

    assert overridden_settings.WEIGHTS_DIR == custom_dir


def test_load_models_reads_weights_dir_from_settings(monkeypatch) -> None:
    """`load_models` must source its checkpoint directory from `settings.WEIGHTS_DIR`
    rather than a path hardcoded relative to `tts_pipeline.py`."""
    import backend.services.tts_pipeline as module

    source = importlib.util.find_spec(module.__name__).origin
    with open(source, "r", encoding="utf-8") as fh:
        source_code = fh.read()

    assert "weights_dir = settings.WEIGHTS_DIR" in source_code
    assert 'os.path.join(os.path.dirname(__file__), "..", "weights")' not in source_code
