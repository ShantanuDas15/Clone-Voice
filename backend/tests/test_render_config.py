"""render.yaml stays consistent with the code and carries no secrets."""

from pathlib import Path

import yaml

from backend.core.config import Settings
from backend.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
TEXT = (REPO_ROOT / "render.yaml").read_text()
BLUEPRINT = yaml.safe_load(TEXT)
SERVICES = {service["name"]: service for service in BLUEPRINT["services"]}
API = SERVICES["clonevoice-api"]
WEB = SERVICES["clonevoice-web"]


def _env(service: dict) -> dict:
    """The service's envVars keyed by name."""
    return {item["key"]: item for item in service["envVars"]}


def test_dockerfiles_exist_and_build_from_the_repo_root():
    for service in (API, WEB):
        assert (REPO_ROOT / service["dockerfilePath"]).is_file()
        assert service["dockerContext"] == "."


def test_api_health_check_is_the_readiness_route():
    assert API["healthCheckPath"] == "/health/ready"
    assert "/health/ready" in {getattr(route, "path", None) for route in app.routes}


def test_api_is_one_instance_with_enough_memory_for_the_models():
    assert API["numInstances"] == 1
    ram_gb = float(API["plan"].split("-")[1].removesuffix("g"))
    assert ram_gb >= 2


def test_migrations_run_before_traffic():
    assert API["preDeployCommand"] == "alembic -c backend/alembic.ini upgrade head"


def test_disk_is_mounted_where_data_dir_points():
    assert API["disk"]["mountPath"] == _env(API)["DATA_DIR"]["value"]


def test_every_api_variable_is_a_real_setting():
    unknown = set(_env(API)) - set(Settings.model_fields)
    assert not unknown


def test_no_secret_is_written_in_the_blueprint():
    for service in (API, WEB):
        for key, item in _env(service).items():
            if "value" in item:
                assert not any(
                    word in key for word in ("SECRET", "KEY", "TOKEN", "PASSWORD")
                ), key
    for key in ("JWT_SECRET_KEY", "SESSION_SECRET_KEY", "METRICS_AUTH_TOKEN"):
        assert _env(API)[key] == {"key": key, "generateValue": True}


def test_database_and_cache_are_wired_over_the_private_network():
    env = _env(API)
    assert env["DATABASE_URL"]["fromDatabase"]["name"] == "clonevoice-db"
    assert env["RATE_LIMIT_STORAGE_URI"]["fromService"]["name"] == "clonevoice-cache"
    assert BLUEPRINT["databases"][0]["ipAllowList"] == []
    assert SERVICES["clonevoice-cache"]["ipAllowList"] == []


def test_web_build_variables_match_the_dockerfile_args():
    dockerfile = (REPO_ROOT / WEB["dockerfilePath"]).read_text()
    for key in _env(WEB):
        assert f"ARG {key}" in dockerfile


def test_runbook_documents_the_unverified_platform_risks():
    doc = (REPO_ROOT / "RENDER_DEPLOYMENT.md").read_text()
    for phrase in ("Disk ownership", "Shutdown delay", "Client IP", "Unverified"):
        assert phrase in doc
