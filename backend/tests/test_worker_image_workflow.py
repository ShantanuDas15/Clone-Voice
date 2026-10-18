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


def _dockerfile_code() -> str:
    """The Dockerfile without comments."""
    return re.sub(r"(?m)^\s*#.*$", "", DOCKERFILE.read_text(encoding="utf-8"))


def test_the_lock_is_installed_as_pinned_and_then_checked():
    """Resolving again fails (chatterbox-tts and the lock name resemble-perth by different URLs)."""
    dockerfile = _dockerfile_code()

    assert (
        "pip install --no-cache-dir --no-deps -r /tmp/requirements.install.txt"
        in dockerfile
    )
    assert "pip check" in dockerfile
    assert "--index-url https://download.pytorch.org/whl/cpu" in dockerfile


def test_cuda_is_the_default_backend_and_a_bad_value_stops_the_build():
    dockerfile = _dockerfile_code()

    assert "ARG TORCH_BACKEND=cuda" in dockerfile
    assert "TORCH_BACKEND must be cuda or cpu" in dockerfile and "exit 1" in dockerfile


def _grep_from_dockerfile(flag: str, pattern_start: str) -> str:
    """The ERE the Dockerfile passes to ``grep``, so the test runs the real filter."""
    match = re.search(rf"grep {flag} '(\^\({pattern_start}[^']*)'", _dockerfile_code())
    assert match, f"no `grep {flag} '^({pattern_start}...'` in the Dockerfile"
    return match.group(1)


def _grep(args: list, text: str) -> list:
    done = subprocess.run(["grep", *args], input=text, text=True, capture_output=True)
    return done.stdout.splitlines()


def test_the_cpu_filter_drops_exactly_the_cuda_runtime_and_keeps_every_other_pin():
    """Docker cannot run here, so run the Dockerfile's own grep patterns on the real lock."""
    lock = (REPO_ROOT / "tts_worker/requirements.lock.txt").read_text(encoding="utf-8")
    keep_torch = _grep_from_dockerfile("-E", "torch")
    drop = _grep_from_dockerfile("-v -E", "nvidia")
    pin = re.compile(r"^[A-Za-z0-9_.-]+(==| @ )")
    all_pins = [line for line in lock.splitlines() if pin.match(line)]

    torch_lines = _grep(["-E", keep_torch], lock)
    kept = _grep(["-v", "-E", drop], lock)
    kept_pins = [line for line in kept if pin.match(line)]
    dropped = sorted(set(all_pins) - set(kept_pins))

    assert torch_lines == [
        "torch==2.6.0",
        "torchaudio==2.6.0",
    ]  # what the CPU index installs
    assert dropped and all(
        re.match(r"(nvidia-[a-z0-9-]+|triton|torch|torchaudio)==", line)
        for line in dropped
    )
    assert any(line.startswith("nvidia-") for line in dropped)
    assert "triton==3.2.0" in dropped
    # Nothing else is lost: every non-CUDA pin (chatterbox-tts, the two Git commits, fastapi...) stays.
    assert len(kept_pins) == len(all_pins) - len(dropped)
    for needed in (
        "chatterbox-tts @",
        "resemble-perth @",
        "fastapi==",
        "transformers==5.2.0",
    ):
        assert any(line.startswith(needed) for line in kept_pins), needed
    assert not [line for line in kept_pins if re.match(r"(nvidia|triton|torch)", line)]


def test_the_workflow_builds_and_checks_both_backends(workflow, steps):
    matrix = workflow["jobs"]["image-and-synthesis"]["strategy"]["matrix"]["include"]
    limits = {entry["torch_backend"]: entry["size_limit_mb"] for entry in matrix}

    assert set(limits) == {"cuda", "cpu"}
    assert limits["cpu"] < limits["cuda"]  # the CPU image has to stay the small one
    assert workflow["jobs"]["image-and-synthesis"]["strategy"]["fail-fast"] is False
    assert '--build-arg TORCH_BACKEND="$TORCH_BACKEND"' in _run(
        steps, "Build the worker image"
    )
    size = _run(steps, "Image size")
    assert 'test "$mb" -le "$SIZE_LIMIT_MB"' in size
    check = _run(steps, "non-root")
    for expected in (
        '"+cpu"',
        'find_spec("nvidia") is None',
        'find_spec("triton") is None',
    ):
        assert expected.replace('"+cpu"', "+cpu") in check, expected


def test_the_lock_pins_the_versions_the_workflow_asserts():
    lock = (REPO_ROOT / "tts_worker/requirements.lock.txt").read_text(encoding="utf-8")

    assert re.search(r"^torch==2\.6\.0\b", lock, re.M)
    assert re.search(r"^transformers==5\.2\.0\b", lock, re.M)
