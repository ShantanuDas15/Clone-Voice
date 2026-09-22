"""Structural validation for the backend's container deployment artifacts.

HARDENING_PLAN.md finding H7: previously there was no Dockerfile at all, and
`docker-compose.yml` defined only a `db` service, so the README's documented
`docker-compose up --build` start path could not actually start the API.

These tests statically assert the shape of `backend/Dockerfile` and
`docker-compose.yml` (single explicit uvicorn worker, healthcheck, non-root
user, the new `backend` service and its volumes/dependency wiring) without
requiring a Docker daemon — this sandbox has the `docker` CLI installed but
no daemon permissions, so a real `docker build`/`run` could not be exercised
here. Where the `docker` CLI *is* available, `test_compose_config_is_valid`
additionally runs `docker compose config` (pure YAML/schema validation, no
daemon or network access) as a stronger check.
"""

import re
import shutil
import subprocess

import pytest

REPO_ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()


def _read(path: str) -> str:
    with open(f"{REPO_ROOT}/{path}", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# backend/Dockerfile
# ---------------------------------------------------------------------------


def test_dockerfile_exists():
    dockerfile = _read("backend/Dockerfile")
    assert dockerfile.strip(), "backend/Dockerfile must not be empty"


def test_dockerfile_uses_explicit_single_worker():
    """HARDENING_PLAN.md H7: the semaphore (H6) and rate limiter (M3) are
    process-local, so the image must pin exactly one uvicorn worker, not
    leave the worker count as an unstated default."""
    dockerfile = _read("backend/Dockerfile")
    assert '"--workers", "1"' in dockerfile
    # Guard against a second, later top-level CMD instruction silently
    # overriding this with a higher worker count. Matches only an
    # instruction at the start of a line, so HEALTHCHECK's own
    # `... \` + `    CMD curl ...` continuation doesn't count as a second one.
    assert len(re.findall(r"^CMD ", dockerfile, re.MULTILINE)) == 1


def test_dockerfile_exposes_port_8000():
    dockerfile = _read("backend/Dockerfile")
    assert "EXPOSE 8000" in dockerfile


def test_dockerfile_declares_a_healthcheck():
    dockerfile = _read("backend/Dockerfile")
    assert "HEALTHCHECK" in dockerfile
    # Liveness, not readiness: a DB/model blip must not mark the container
    # unhealthy and trigger restarts (HARDENING_PLAN.md finding M7).
    assert "/health/live" in dockerfile


def test_dockerfile_runs_as_non_root_user():
    dockerfile = _read("backend/Dockerfile")
    assert "USER appuser" in dockerfile
    assert "USER root" not in dockerfile


def test_dockerfile_does_not_bake_in_env_file():
    """Secrets must come from `docker-compose.yml`'s `env_file:` at
    container-start time, never be COPYed into the image."""
    dockerfile = _read("backend/Dockerfile")
    assert ".env" not in dockerfile


def test_dockerfile_installs_audio_system_dependencies():
    """`soundfile` (libsndfile1) and MP3/WEBM decoding via librosa/audioread
    (ffmpeg) are hard runtime requirements — see audio_processing.py and
    tts_pipeline.py's `save_output()` — not optional extras."""
    dockerfile = _read("backend/Dockerfile")
    assert "libsndfile1" in dockerfile
    assert "ffmpeg" in dockerfile


# ---------------------------------------------------------------------------
# .dockerignore
# ---------------------------------------------------------------------------


def test_dockerignore_excludes_secrets_and_user_data():
    dockerignore = _read(".dockerignore")
    for pattern in (".env", "weights/", "uploads/", "outputs/"):
        assert pattern in dockerignore


def test_dockerignore_does_not_drop_vendored_license_notice():
    """The vendored SV2TTS code's MIT license requires
    backend/services/sv2tts/THIRD_PARTY_NOTICE.md to ship alongside it — a
    blanket `*.md` ignore pattern would silently drop it from the build
    context along with the top-level docs that are genuinely unneeded."""
    dockerignore = _read(".dockerignore")
    assert not re.search(r"^\*\.md$", dockerignore, re.MULTILINE)
    code_lines = "\n".join(
        line for line in dockerignore.splitlines() if not line.strip().startswith("#")
    )
    assert "THIRD_PARTY_NOTICE" not in code_lines


# ---------------------------------------------------------------------------
# docker-compose.yml
# ---------------------------------------------------------------------------


def _backend_service_block() -> str:
    """Return the `backend:` service's YAML block from docker-compose.yml.

    Uses plain text slicing rather than a YAML parser: PyYAML happens to be
    present in this venv as a transitive dependency (of `uvicorn[standard]`)
    but isn't pinned directly in `requirements.txt`, so relying on it here
    would make this test fragile to unrelated dependency changes. The
    `backend:` service block runs from its own two-space-indented header
    to the next top-level (`volumes:`) key.
    """
    compose = _read("docker-compose.yml")
    match = re.search(r"\n  backend:\n(.*?)\nvolumes:\n", compose, re.DOTALL)
    assert match, "Could not locate a `backend:` service block in docker-compose.yml"
    return match.group(1)


def _db_service_block() -> str:
    """Return the `db:` service's YAML block from docker-compose.yml, using
    the same text-slicing approach as `_backend_service_block` (see its
    docstring). Runs from its own header to the next top-level (`redis:`)
    service key."""
    compose = _read("docker-compose.yml")
    match = re.search(r"\n  db:\n(.*?)\n  redis:\n", compose, re.DOTALL)
    assert match, "Could not locate a `db:` service block in docker-compose.yml"
    return match.group(1)


def test_compose_defines_backend_service():
    compose = _read("docker-compose.yml")
    assert re.search(r"^  backend:$", compose, re.MULTILINE)


def test_compose_db_password_is_not_hardcoded():
    """HARDENING_PLAN.md finding L12: the DB password must come from the
    environment via `${POSTGRES_PASSWORD:-...}` substitution, not assigned
    as a bare literal — even a documented dev-only default shouldn't be a
    fixed literal that's identical across every clone of this repo."""
    db = _db_service_block()
    password_line = next(
        line
        for line in db.splitlines()
        if line.strip().startswith("POSTGRES_PASSWORD:")
    )
    assert re.search(r"POSTGRES_PASSWORD:\s*\$\{POSTGRES_PASSWORD\b", password_line)


def test_compose_db_port_bound_to_localhost_only():
    """The published port must not be reachable from outside the host —
    `"5432:5432"` (binds 0.0.0.0) must become `"127.0.0.1:5432:5432"`."""
    db = _db_service_block()
    port_line = next(line for line in db.splitlines() if "5432" in line)
    assert "127.0.0.1" in port_line


def test_compose_backend_database_url_shares_the_same_postgres_vars():
    """The `backend` service's DATABASE_URL override must be built from the
    same `POSTGRES_*` variables as the `db` service, not a second hardcoded
    copy of the credentials that could silently drift out of sync."""
    backend = _backend_service_block()
    database_url_line = next(
        line for line in backend.splitlines() if "DATABASE_URL:" in line
    )
    assert "${POSTGRES_USER" in database_url_line
    assert "${POSTGRES_PASSWORD" in database_url_line
    assert "${POSTGRES_DB" in database_url_line


def test_root_env_example_documents_postgres_variables():
    """A root `.env.example` (distinct from `backend/.env.example`) must
    document the compose-level variables and their dev-only defaults."""
    root_env_example = _read(".env.example")
    for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_PORT"):
        assert key in root_env_example


@pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker CLI not available in this environment",
)
def test_compose_config_resolves_db_port_to_localhost_only():
    """Beyond static text checks, confirm `docker compose config` actually
    resolves the port mapping's `host_ip` to `127.0.0.1` (no daemon needed —
    see `test_compose_config_is_valid`)."""
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            f"{REPO_ROOT}/docker-compose.yml",
            "config",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "host_ip: 127.0.0.1" in result.stdout


def test_compose_backend_builds_from_repo_root_with_backend_dockerfile():
    backend = _backend_service_block()
    assert re.search(r"context:\s*\.\s*$", backend, re.MULTILINE)
    assert re.search(r"dockerfile:\s*backend/Dockerfile\s*$", backend, re.MULTILINE)


def test_compose_backend_depends_on_healthy_db():
    backend = _backend_service_block()
    assert "depends_on" in backend
    assert re.search(r"condition:\s*service_healthy", backend)


def test_compose_backend_does_not_scale_replicas():
    """Guards against a `deploy.replicas` override reintroducing the
    multi-process-state bug the single-worker Dockerfile CMD avoids
    (HARDENING_PLAN.md H6/M3)."""
    backend = _backend_service_block()
    match = re.search(r"replicas:\s*(\d+)", backend)
    assert match is None or match.group(1) == "1"


def test_compose_backend_exposes_port_8000():
    backend = _backend_service_block()
    assert "8000" in backend


def test_compose_backend_persists_weights_uploads_outputs_as_volumes():
    """Model checkpoints and user data must survive `docker-compose down` /
    a container rebuild — see .dockerignore, which deliberately excludes
    them from the image itself."""
    backend = _backend_service_block()
    assert "weights" in backend
    assert "uploads" in backend
    assert "outputs" in backend


def test_compose_backend_reads_secrets_from_env_file_not_hardcoded():
    backend = _backend_service_block()
    assert "backend/.env" in backend
    # DATABASE_URL is legitimately overridden here (compose-network hostname
    # `db`, not `localhost`) — but no *secret* value should be hardcoded as
    # an actual `KEY: value` entry. Strip comment lines first so an
    # explanatory `# ... JWT_SECRET_KEY ...` comment doesn't false-positive.
    code_lines = "\n".join(
        line for line in backend.splitlines() if not line.strip().startswith("#")
    )
    for key in ("JWT_SECRET_KEY", "GOOGLE_CLIENT_SECRET"):
        assert key not in code_lines


@pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker CLI not available in this environment",
)
def test_compose_config_is_valid():
    """`docker compose config` only parses and validates the YAML/schema —
    it needs the `docker` CLI but not daemon access or network calls, so
    it's safe to run in a plain test environment."""
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            f"{REPO_ROOT}/docker-compose.yml",
            "config",
            "--quiet",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
