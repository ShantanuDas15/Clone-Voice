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


def _settings_with(monkeypatch, **env: str) -> Settings:
    """Build a Settings instance with the given env overrides."""
    monkeypatch.setenv("DATABASE_URL", settings.DATABASE_URL)
    monkeypatch.setenv("JWT_SECRET_KEY", settings.JWT_SECRET_KEY)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings()


def test_storage_dirs_default_to_backend_directory(monkeypatch) -> None:
    """Without overrides, UPLOAD_DIR/OUTPUT_DIR live under BASE_DIR."""
    monkeypatch.delenv("UPLOAD_DIR", raising=False)
    monkeypatch.delenv("OUTPUT_DIR", raising=False)
    cfg = Settings(_env_file=None, DATABASE_URL="sqlite://", JWT_SECRET_KEY="x" * 40)

    assert cfg.UPLOAD_DIR == str(BASE_DIR / "uploads")
    assert cfg.OUTPUT_DIR == str(BASE_DIR / "outputs")


def test_relative_storage_dirs_are_anchored_to_base_dir_not_cwd(
    monkeypatch, tmp_path
) -> None:
    """A relative value resolves against BASE_DIR even if the CWD differs."""
    monkeypatch.chdir(tmp_path)
    cfg = _settings_with(monkeypatch, UPLOAD_DIR="uploads", OUTPUT_DIR="data/out")

    assert cfg.UPLOAD_DIR == str(BASE_DIR / "uploads")
    assert cfg.OUTPUT_DIR == str(BASE_DIR / "data" / "out")


def test_absolute_storage_dirs_are_kept_as_is(monkeypatch, tmp_path) -> None:
    """An absolute value is not re-anchored."""
    cfg = _settings_with(
        monkeypatch, UPLOAD_DIR=str(tmp_path / "u"), OUTPUT_DIR=str(tmp_path / "o")
    )

    assert cfg.UPLOAD_DIR == str(tmp_path / "u")
    assert cfg.OUTPUT_DIR == str(tmp_path / "o")


def test_blank_storage_dir_is_rejected(monkeypatch) -> None:
    """An empty path would resolve to BASE_DIR itself, so it must be refused."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _settings_with(monkeypatch, UPLOAD_DIR="  ")


def test_tests_never_write_into_real_storage_dirs(tmp_path) -> None:
    """The autouse fixture redirects storage into the per-test temp dir."""
    assert settings.UPLOAD_DIR == str(tmp_path / "uploads")
    assert settings.OUTPUT_DIR == str(tmp_path / "outputs")
