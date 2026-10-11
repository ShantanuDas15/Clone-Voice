"""The S4.2 engine decision record stays complete and enforces the licence gate."""

import json
import typing
from pathlib import Path

import pytest

from backend.core.config import Settings

RECORD = Path(__file__).resolve().parents[1] / "eval_data" / "engine_candidates.json"
REQUIRED = {
    "id",
    "name",
    "code_license",
    "weights_license",
    "licence",
    "benchmarked",
    "decision",
    "evidence",
    "notes",
}
LICENCES = {"ok", "unclear", "blocked"}
DECISIONS = {"candidate", "unassessed", "rejected"}


@pytest.fixture(scope="module")
def record() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8"))


def test_the_record_declares_when_it_was_checked_and_how(record):
    assert record["checked"] and record["method"]
    assert set(record["licence_values"]) == LICENCES
    assert set(record["decision_values"]) == DECISIONS


def test_every_candidate_has_every_field_and_valid_values(record):
    ids = [c["id"] for c in record["candidates"]]
    assert len(ids) == len(set(ids))
    for c in record["candidates"]:
        assert REQUIRED <= set(c), c["id"]
        assert c["licence"] in LICENCES and c["decision"] in DECISIONS, c["id"]
        assert isinstance(c["benchmarked"], bool), c["id"]
        assert c["notes"].strip(), c["id"]


def test_every_claim_cites_a_primary_page(record):
    for c in record["candidates"]:
        assert c["evidence"], c["id"]
        assert all(u.startswith("https://") for u in c["evidence"]), c["id"]


def test_a_blocked_licence_is_always_rejected(record):
    for c in record["candidates"]:
        if c["licence"] == "blocked":
            assert c["decision"] == "rejected", c["id"]


def test_only_a_licence_ok_benchmarked_engine_can_be_a_candidate(record):
    for c in record["candidates"]:
        if c["decision"] == "candidate":
            assert c["licence"] == "ok" and c["benchmarked"], c["id"]


def test_an_unassessed_engine_has_not_been_benchmarked(record):
    for c in record["candidates"]:
        if c["decision"] == "unassessed":
            assert not c["benchmarked"] and c["licence"] != "blocked", c["id"]


def test_every_selectable_engine_is_the_baseline_or_licence_ok_in_the_record(record):
    """Licences are a gate (plan section 3, rule 6): TTS_ENGINE cannot name an engine whose
    licence was not recorded as ok. sv2tts is the in-repository baseline."""
    selectable = set(typing.get_args(Settings.model_fields["TTS_ENGINE"].annotation))
    by_id = {c["id"]: c for c in record["candidates"]}
    for engine in selectable - {"sv2tts"}:
        assert engine in by_id, f"{engine} is selectable but not in the decision record"
        assert by_id[engine]["licence"] == "ok", engine
        assert by_id[engine]["decision"] == "candidate", engine


def test_the_baseline_is_selectable():
    assert "sv2tts" in typing.get_args(Settings.model_fields["TTS_ENGINE"].annotation)
