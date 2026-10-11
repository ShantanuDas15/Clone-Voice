"""Canary rollout of a second engine to a share of users (SPEECH_QUALITY_PLAN.md S7.4a)."""

import uuid

import pytest

from backend.core.config import Settings, settings
from backend.services import tts_engine
from backend.services.tts_engine import canary_bucket, get_engine_for_user

URL = "http://localhost:9000"
TOKEN = "t" * 40


@pytest.fixture
def canary(monkeypatch):
    """A canary on the in-process engine pair, so no worker is needed."""
    monkeypatch.setattr(settings, "TTS_ENGINE", "sv2tts")
    monkeypatch.setattr(settings, "TTS_CANARY_ENGINE", "chatterbox_nano")
    monkeypatch.setattr(settings, "TTS_WORKER_URL", URL)
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)


def _users(n=400):
    return [str(uuid.uuid4()) for _ in range(n)]


def test_the_bucket_is_stable_and_in_range():
    user = str(uuid.uuid4())
    assert canary_bucket(user) == canary_bucket(user)
    assert all(0 <= canary_bucket(u) < 100 for u in _users())


def test_off_by_default_everyone_gets_the_main_engine(canary, monkeypatch):
    assert settings.TTS_CANARY_PERCENT == 0
    assert {get_engine_for_user(u).name for u in _users(50)} == {"sv2tts"}


def test_a_hundred_percent_moves_everyone(canary, monkeypatch):
    monkeypatch.setattr(settings, "TTS_CANARY_PERCENT", 100)
    assert {get_engine_for_user(u).name for u in _users(50)} == {"chatterbox_nano"}


def test_the_share_is_about_the_percentage_and_a_user_never_flips(canary, monkeypatch):
    monkeypatch.setattr(settings, "TTS_CANARY_PERCENT", 25)
    users = _users(1000)
    first = [get_engine_for_user(u).name for u in users]
    share = first.count("chatterbox_nano") / len(users)
    assert 0.18 < share < 0.32
    assert first == [get_engine_for_user(u).name for u in users]


def test_raising_the_percentage_only_adds_users(canary, monkeypatch):
    users = _users(500)
    monkeypatch.setattr(settings, "TTS_CANARY_PERCENT", 10)
    low = {u for u in users if get_engine_for_user(u).name == "chatterbox_nano"}
    monkeypatch.setattr(settings, "TTS_CANARY_PERCENT", 50)
    high = {u for u in users if get_engine_for_user(u).name == "chatterbox_nano"}
    assert low <= high and len(high) > len(low)


def test_an_engine_swapped_in_for_get_engine_is_still_honoured(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(tts_engine, "get_engine", lambda: sentinel)
    assert get_engine_for_user("anyone") is sentinel


def test_a_canary_on_a_worker_engine_needs_the_worker_settings():
    with pytest.raises(ValueError, match="TTS_WORKER_URL"):
        Settings(TTS_CANARY_ENGINE="chatterbox", TTS_CANARY_PERCENT=5)
    Settings(TTS_CANARY_ENGINE="chatterbox", TTS_CANARY_PERCENT=0)


@pytest.mark.parametrize("percent", [-1, 101])
def test_the_percentage_is_bounded(percent):
    with pytest.raises(ValueError):
        Settings(TTS_CANARY_PERCENT=percent)
