"""The frontend's committed OpenAPI snapshot must match the live app schema."""

from backend.export_openapi import SNAPSHOT_PATH, main, render_schema


def test_snapshot_matches_the_live_schema():
    assert SNAPSHOT_PATH.exists(), "run: python -m backend.export_openapi"
    assert SNAPSHOT_PATH.read_text() == render_schema()


def test_check_flag_passes_when_current():
    assert main(["--check"]) == 0


def test_check_flag_fails_when_stale(tmp_path, monkeypatch):
    stale = tmp_path / "openapi.json"
    stale.write_text("{}\n")
    monkeypatch.setattr("backend.export_openapi.SNAPSHOT_PATH", stale)
    assert main(["--check"]) == 1


def test_check_flag_fails_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.export_openapi.SNAPSHOT_PATH", tmp_path / "none.json")
    assert main(["--check"]) == 1
