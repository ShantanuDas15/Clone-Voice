"""railway.toml and RAILWAY_DEPLOYMENT.md stay consistent with the code
(HARDENING_PLAN.md R1). The platform itself can't be run here, so these guard
the parts that can silently drift."""

import re
import tomllib
from pathlib import Path

import pytest

from backend.core.config import Settings
from backend.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = tomllib.loads((REPO_ROOT / "railway.toml").read_text())
DOC = (REPO_ROOT / "RAILWAY_DEPLOYMENT.md").read_text()


def test_builds_the_backend_dockerfile_from_the_repo_root():
    build = CONFIG["build"]
    assert build["builder"] == "DOCKERFILE"
    assert (REPO_ROOT / build["dockerfilePath"]).is_file()


def test_healthcheck_path_is_a_real_unauthenticated_route():
    path = CONFIG["deploy"]["healthcheckPath"]
    assert path in {getattr(route, "path", None) for route in app.routes}
    # Readiness (DB, schema, models), so a broken deploy never goes live.
    assert path == "/health/ready"


def test_healthcheck_timeout_allows_a_first_boot_weights_download():
    assert CONFIG["deploy"]["healthcheckTimeout"] >= 300


def test_migrations_run_before_the_new_version_takes_traffic():
    (command,) = CONFIG["deploy"]["preDeployCommand"]
    assert command == "alembic -c backend/alembic.ini upgrade head"
    assert (REPO_ROOT / "backend" / "alembic.ini").is_file()


def test_draining_covers_graceful_timeout_and_inference_drain():
    """Same invariant as docker-compose's stop_grace_period (P2-L4): a shorter
    drain lets the platform SIGKILL an in-flight synthesis."""
    from backend.serve import GRACEFUL_SHUTDOWN_SECONDS

    drain = Settings.model_fields["INFERENCE_SHUTDOWN_DRAIN_TIMEOUT_SECONDS"].default
    assert CONFIG["deploy"]["drainingSeconds"] > GRACEFUL_SHUTDOWN_SECONDS + drain


def test_railway_toml_carries_no_secrets():
    text = (REPO_ROOT / "railway.toml").read_text()
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    assert "[variables]" not in code
    assert not re.search(r"(SECRET|PASSWORD|API_KEY|TOKEN)\s*=", code)


def test_dockerfile_healthcheck_follows_the_injected_port():
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text()
    assert "${PORT:-8000}" in dockerfile.split("HEALTHCHECK", 1)[1]


# Variables the platform sets or that are not application settings.
PLATFORM_VARIABLES = {"RAILWAY_RUN_UID", "PORT", "DATABASE_URL_NOTE"}
REQUIRED_IN_DOC = [
    "DATABASE_URL",
    "JWT_SECRET_KEY",
    "SESSION_SECRET_KEY",
    "DATA_DIR",
    "FETCH_WEIGHTS_ON_START",
    "RAILWAY_RUN_UID",
    "TRUSTED_PROXY_COUNT",
    "ALLOWED_ORIGINS",
    "FRONTEND_URL",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI",
    "EMAIL_BACKEND",
    "EMAIL_FROM",
    "RESEND_API_KEY",
    "METRICS_AUTH_TOKEN",
]


@pytest.mark.parametrize("name", REQUIRED_IN_DOC)
def test_deployment_doc_lists_each_required_variable(name):
    assert f"`{name}`" in DOC


def test_every_setting_named_in_the_doc_exists():
    """A renamed or removed setting must not linger in the runbook."""
    named = set(re.findall(r"^\| `([A-Z][A-Z0-9_]+)`", DOC, re.MULTILINE))
    assert named, "the variables table was not found"
    unknown = named - set(Settings.model_fields) - PLATFORM_VARIABLES
    assert not unknown, f"documented but not a setting: {sorted(unknown)}"


def test_doc_states_the_volume_permission_requirement():
    assert "RAILWAY_RUN_UID=0" in DOC
    assert "/data" in DOC


def test_env_example_documents_the_new_settings():
    example = (REPO_ROOT / "backend" / ".env.example").read_text()
    for name in ("DATA_DIR", "FETCH_WEIGHTS_ON_START"):
        assert name in example


def test_ci_exercises_the_entrypoint_on_real_docker():
    workflow = (REPO_ROOT / ".github" / "workflows" / "docker-build.yml").read_text()
    assert "backend.serve --dry-run" in workflow
    assert "RAILWAY_RUN_UID=0" in workflow
    # Changing the entrypoint or the config must trigger that job.
    assert '"backend/serve.py"' in workflow and '"railway.toml"' in workflow


# --- the inference worker service (CHATTERBOX_ROLLOUT_PLAN.md R0.4) ---------------------------

WORKER_CONFIG = tomllib.loads((REPO_ROOT / "tts_worker" / "railway.toml").read_text())
RUNBOOK = (REPO_ROOT / "CHATTERBOX_RUNBOOK.md").read_text()


def test_worker_builds_its_own_dockerfile_from_the_repo_root():
    build = WORKER_CONFIG["build"]
    assert build["builder"] == "DOCKERFILE"
    assert (REPO_ROOT / build["dockerfilePath"]).is_file()
    assert build["dockerfilePath"].startswith("tts_worker/")
    assert WORKER_CONFIG["build"]["watchPatterns"] == ["tts_worker/**"]


def test_worker_healthcheck_is_its_real_unauthenticated_route():
    from tts_worker.app import PATH_HEALTH

    assert WORKER_CONFIG["deploy"]["healthcheckPath"] == PATH_HEALTH
    # The first start downloads the model weights.
    assert WORKER_CONFIG["deploy"]["healthcheckTimeout"] >= 300


def test_worker_draining_outlasts_one_worker_call():
    drain = WORKER_CONFIG["deploy"]["drainingSeconds"]
    assert drain > Settings.model_fields["TTS_WORKER_TIMEOUT_SECONDS"].default


def test_worker_railway_toml_carries_no_secrets():
    text = (REPO_ROOT / "tts_worker" / "railway.toml").read_text()
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    assert "[variables]" not in code
    assert not re.search(r"(SECRET|PASSWORD|API_KEY|TOKEN)\s*=", code)


def test_the_port_in_the_runbook_is_the_one_the_image_listens_on():
    dockerfile = (REPO_ROOT / "tts_worker" / "Dockerfile").read_text()
    assert "EXPOSE 8100" in dockerfile and '"8100"' in dockerfile
    assert "http://tts-worker.railway.internal:8100" in RUNBOOK
    assert "http://tts-worker.railway.internal:8100" in DOC


def test_the_runbook_names_every_variable_the_worker_and_the_api_need():
    for name in (
        "TORCH_BACKEND",
        "TTS_WORKER_TOKEN",
        "TTS_WORKER_MODEL",
        "TTS_WORKER_DEVICE",
        "OMP_NUM_THREADS",
        "TTS_WORKER_URL",
        "TTS_WORKER_ALLOW_PRIVATE_HTTP",
        "TTS_CANARY_ENGINE",
        "TTS_CANARY_PERCENT",
        "TTS_FALLBACK_ENGINE",
    ):
        assert f"`{name}`" in RUNBOOK


def test_the_documented_private_url_passes_the_real_settings_validation():
    """The values the runbook tells the owner to set must start the API."""
    settings = Settings(
        TTS_ENGINE="chatterbox_nano",
        TTS_WORKER_URL="http://tts-worker.railway.internal:8100",
        TTS_WORKER_ALLOW_PRIVATE_HTTP=True,
        TTS_WORKER_TOKEN="x" * 48,
    )
    assert settings.TTS_WORKER_URL.endswith(":8100")
    with pytest.raises(Exception):  # the flag really is required
        Settings(
            TTS_ENGINE="chatterbox_nano",
            TTS_WORKER_URL="http://tts-worker.railway.internal:8100",
            TTS_WORKER_TOKEN="x" * 48,
        )


def test_the_runbook_fallback_reasons_match_the_metric():
    from backend.core import metrics

    source = Path(metrics.__file__).read_text()
    for reason in ("unavailable", "busy", "circuit_open", "reference"):
        assert reason in source and f"`{reason}`" in RUNBOOK
