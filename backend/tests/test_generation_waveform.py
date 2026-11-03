"""H4: waveform peaks of a generation, stored at save time and returned by the history."""

import os
import uuid

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from backend.models.generation import Generation
from backend.services.tts_pipeline import load_mock_models
from backend.services.waveform import (
    PEAK_SCALE,
    WAVEFORM_BARS,
    bucket_peaks,
    compute_waveform_peaks,
)
from backend.tests.test_generation_delete import _generate, _sign_in
from backend.tests.test_synthesize import upload_profile


@pytest.fixture(scope="module", autouse=True)
def mock_models():
    """Inject lightweight mock models once for this module."""
    load_mock_models("cpu")


class TestBucketPeaks:
    """Unit: the reduction from samples to bar heights."""

    def test_loudest_bar_is_the_scale_and_length_is_bars(self):
        samples = np.concatenate([np.full(100, 0.1), np.full(100, 0.4)]).astype(
            np.float32
        )
        peaks = bucket_peaks(samples, 4)
        assert peaks == [25, 25, PEAK_SCALE, PEAK_SCALE]

    def test_negative_samples_count_by_magnitude(self):
        assert bucket_peaks(np.array([-0.5, 0.25], dtype=np.float32), 2) == [100, 50]

    def test_silence_and_empty_give_none(self):
        assert bucket_peaks(np.zeros(500, dtype=np.float32), 8) is None
        assert bucket_peaks(np.array([], dtype=np.float32), 8) is None

    def test_fewer_samples_than_bars_still_returns_a_list(self):
        peaks = bucket_peaks(np.array([0.5, 1.0], dtype=np.float32), 8)
        assert peaks is not None and max(peaks) == PEAK_SCALE


class TestComputeWaveformPeaks:
    """Unit: reading a file, with failures contained."""

    def test_reads_a_wav(self, tmp_path):
        path = str(tmp_path / "a.wav")
        sf.write(path, 0.5 * np.sin(np.linspace(0, 200, 24000)), 24000)
        peaks = compute_waveform_peaks(path)
        assert peaks is not None and len(peaks) == WAVEFORM_BARS
        assert max(peaks) == PEAK_SCALE and all(0 <= p <= PEAK_SCALE for p in peaks)

    def test_missing_or_corrupt_file_is_none_not_an_error(self, tmp_path):
        assert compute_waveform_peaks(str(tmp_path / "nope.wav")) is None
        bad = tmp_path / "bad.wav"
        bad.write_bytes(b"not audio")
        assert compute_waveform_peaks(str(bad)) is None


@pytest.fixture
def headers(client: TestClient) -> dict:
    """Auth headers for a dedicated user."""
    return _sign_in(client, "waveform@example.com")


class TestHistoryPeaks:
    """Integration: stored on save, returned by the history, scrubbed on delete."""

    def test_history_returns_peaks_for_a_new_generation(
        self, client, headers, db_session, monkeypatch
    ):
        # The mock vocoder is silent (no peaks), so stand in a known shape for the file read.
        shape = list(range(WAVEFORM_BARS))
        monkeypatch.setattr(
            "backend.api.synthesize.compute_waveform_peaks", lambda _path: shape
        )
        profile_id = upload_profile(client, headers)
        generation_id = _generate(client, headers, profile_id, "Hello waveform")
        row = db_session.get(Generation, uuid.UUID(generation_id))
        assert row.waveform_peaks == shape
        item = next(
            i
            for i in client.get("/api/v1/synthesize/history", headers=headers).json()
            if i["id"] == generation_id
        )
        assert item["waveform_peaks"] == row.waveform_peaks

    def test_peaks_are_hidden_once_the_audio_is_gone(self, client, headers, db_session):
        profile_id = upload_profile(client, headers)
        generation_id = _generate(client, headers, profile_id, "Expiring clip")
        row = db_session.get(Generation, uuid.UUID(generation_id))
        row.waveform_peaks = [10] * WAVEFORM_BARS
        db_session.commit()
        os.remove(row.output_audio_path)
        item = next(
            i
            for i in client.get("/api/v1/synthesize/history", headers=headers).json()
            if i["id"] == generation_id
        )
        assert item["audio_available"] is False
        assert item["waveform_peaks"] is None

    def test_delete_scrubs_the_peaks(self, client, headers, db_session):
        profile_id = upload_profile(client, headers)
        generation_id = _generate(client, headers, profile_id, "Delete my shape")
        row = db_session.get(Generation, uuid.UUID(generation_id))
        row.waveform_peaks = [10] * WAVEFORM_BARS
        db_session.commit()
        res = client.delete(f"/api/v1/synthesize/{generation_id}", headers=headers)
        assert res.status_code == 204
        db_session.expire_all()
        assert (
            db_session.get(Generation, uuid.UUID(generation_id)).waveform_peaks is None
        )

    def test_a_failure_computing_peaks_never_fails_the_generation(
        self, client, headers, monkeypatch
    ):
        def boom(*_a, **_k):
            raise RuntimeError("decoder exploded")

        monkeypatch.setattr("backend.services.waveform.sf.read", boom)
        profile_id = upload_profile(client, headers)
        res = client.post(
            "/api/v1/synthesize",
            headers=headers,
            json={"voice_profile_id": profile_id, "text": "Still works"},
        )
        assert res.status_code == 200
