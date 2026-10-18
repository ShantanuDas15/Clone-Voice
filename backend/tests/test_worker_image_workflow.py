"""The inference worker image is built and smoke-tested in CI (CHATTERBOX_ROLLOUT_PLAN.md R0.1).

These tests read the workflow and the Dockerfile as files: they cannot run Docker, but they keep the
workflow from quietly losing the checks that make it worth running.
"""

import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
)
WORKFLOW = REPO_ROOT / ".github/workflows/worker-docker-build.yml"
DOCKERFILE = REPO_ROOT / "tts_worker/Dockerfile"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def steps(workflow) -> dict:
    """The job's steps by name."""
    job = workflow["jobs"]["image-and-synthesis"]
    return {step["name"]: step for step in job["steps"] if "name" in step}


def _run(steps: dict, fragment: str) -> str:
    """The shell of the one step whose name contains ``fragment``."""
    matches = [s["run"] for name, s in steps.items() if fragment in name and "run" in s]
    assert len(matches) == 1, f"expected exactly one step named like {fragment!r}"
    return matches[0]


def test_it_runs_on_worker_changes_weekly_and_on_demand(workflow):
    triggers = workflow[True]  # PyYAML reads the bare key `on` as True
    paths = triggers["push"]["paths"]

    assert "tts_worker/**" in paths
    assert ".github/workflows/worker-docker-build.yml" in paths
    assert ".dockerignore" in paths
    assert "workflow_dispatch" in triggers and triggers["schedule"][0]["cron"]


def test_it_is_least_privilege_and_bounded(workflow):
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["image-and-synthesis"]["timeout-minutes"] <= 90


def test_it_builds_the_worker_dockerfile_from_the_repo_root(steps):
    build = _run(steps, "Build the worker image")

    assert "docker build -f tts_worker/Dockerfile" in build
    assert build.rstrip().endswith(".")  # the context is the repo root


def test_it_frees_disk_before_building(steps):
    names = list(steps)

    assert names.index("Free disk space") < names.index("Build the worker image")


def test_the_image_is_checked_for_user_secret_and_pins(steps):
    check = _run(steps, "non-root")

    assert '"10001"' in check  # the Dockerfile's worker user
    assert "TTS_WORKER_TOKEN" in check  # it must not be baked in
    assert "docker run --rm -i" in check  # -i, or the heredoc never reaches Python
    for pin in ("2.6.0", "5.2.0", "pkg_resources"):
        assert pin in check


def test_the_worker_starts_on_cpu_with_a_random_masked_token(steps):
    start = _run(steps, "Start the worker")

    assert "openssl rand" in start and "::add-mask::" in start
    assert "TTS_WORKER_MODEL=nano" in start and "TTS_WORKER_DEVICE=cpu" in start
    assert not re.search(r"TTS_WORKER_TOKEN=[A-Za-z0-9]{16,}", start)  # nothing literal


def test_it_waits_for_health_and_checks_the_reported_model(steps):
    wait = _run(steps, "Wait for the model")

    assert "/health" in wait and "docker logs" in wait
    assert '"model": "nano"' in wait and '"sample_rate": 24000' in wait


def test_the_request_checks_cover_auth_model_and_reference(steps):
    checks = _run(steps, "Authentication and request checks")

    for expected in ('"401"', '"409"', '"422"'):
        assert expected in checks
    assert "Bearer wrong" in checks and "model=turbo" in checks


def test_it_makes_one_real_synthesis_and_inspects_the_audio(steps):
    synthesis = _run(steps, "One real synthesis")

    assert "/v1/synthesize" in synthesis and "reference=@ref.wav" in synthesis
    assert "response body" in synthesis  # a failure shows the worker's reason
    assert "x-sample-rate: 24000" in synthesis.lower()
    assert "(3, 1, 24000, 32)" in synthesis  # 32-bit float, mono, 24 kHz


def test_it_checks_the_privacy_promises_of_the_worker(steps):
    privacy = _run(steps, "Nothing private")

    assert 'grep -qF "$SMOKE_TEXT"' in privacy and 'grep -qF "$TOKEN"' in privacy
    assert "/tmp/*.wav" in privacy


def test_cleanup_and_diagnostics_run_even_after_a_failure(steps):
    assert steps["Tear down"]["if"] == "always()"
    assert steps["Worker logs (diagnostics)"]["if"] == "always()"


def test_the_smoke_reference_is_longer_than_the_models_five_second_minimum(
    workflow, steps
):
    """Turbo and Nano assert `len(reference) / sr > 5.0`: a 5.0 second clip is rejected (422)."""
    seconds = int(workflow["env"]["REFERENCE_SECONDS"])
    make = _run(steps, "Make a reference clip")

    assert seconds > 5
    assert "REFERENCE_SECONDS" in make and "ref.wav" in make
    assert "sample_5sec" not in WORKFLOW.read_text(encoding="utf-8")


def test_the_dockerfile_matches_what_the_workflow_assumes():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "--uid 10001" in dockerfile and "USER worker" in dockerfile
    assert "TTS_WORKER_MODEL=nano" in dockerfile and "EXPOSE 8100" in dockerfile
    assert "TTS_WORKER_TOKEN" not in re.sub(r"#.*", "", dockerfile)  # only in comments
    assert "worker-docker-build.yml" in dockerfile
    assert "NOT BUILT" not in dockerfile


def test_the_lock_is_installed_as_pinned_and_then_checked():
    """Resolving again fails (chatterbox-tts and the lock name resemble-perth by different URLs)."""
    dockerfile = re.sub(r"#.*", "", DOCKERFILE.read_text(encoding="utf-8"))

    assert (
        "pip install --no-cache-dir --no-deps -r /tmp/requirements.lock.txt"
        in dockerfile
    )
    assert "pip check" in dockerfile


def test_the_lock_pins_the_versions_the_workflow_asserts():
    lock = (REPO_ROOT / "tts_worker/requirements.lock.txt").read_text(encoding="utf-8")

    assert re.search(r"^torch==2\.6\.0\b", lock, re.M)
    assert re.search(r"^transformers==5\.2\.0\b", lock, re.M)
