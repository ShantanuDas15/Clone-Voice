"""The CI/CD pipeline (RAILWAY_DEPLOYMENT.md, "Automatic deploys").

Two kinds of test, both hermetic (no network, no Railway, no GitHub, nothing left behind):

* structural: the workflow cannot deploy from a pull request, holds no write permission, never prints
  the Railway token, waits only for checks that really exist, and deploys the API before the web app;
* behavioural: the real scripts in ``scripts/ci`` run against fake ``gh``, ``curl`` and ``railway``
  programs and temporary git repositories, so every branch (passed, failed, still running, timed out)
  is exercised for real.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts" / "ci"
WORKFLOWS = REPO / ".github" / "workflows"

needs_tools = pytest.mark.skipif(
    not (shutil.which("bash") and shutil.which("jq") and shutil.which("git")),
    reason="bash, jq and git are needed to run the CI scripts",
)


def load(name: str) -> dict:
    """Parse a workflow file (PyYAML reads the bare key ``on`` as the boolean True)."""
    data = yaml.safe_load((WORKFLOWS / name).read_text())
    data["on"] = data.pop(True, data.get("on"))
    return data


# --------------------------------------------------------------------------- structural


def test_a_pull_request_can_never_deploy() -> None:
    """Only a push to main or a manual run triggers it; a PR (even from a fork) never does."""
    triggers = load("deploy.yml")["on"]
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"] == {"branches": ["main"]}


def test_it_holds_no_write_permission() -> None:
    """It reads the repository and check results; nothing in GitHub is changed by it."""
    assert load("deploy.yml")["permissions"] == {"contents": "read", "checks": "read"}


def test_deploys_queue_one_at_a_time_and_a_newer_push_never_cancels_one_midway() -> (
    None
):
    """Cancelling a deploy halfway would leave a service between versions."""
    assert load("deploy.yml")["concurrency"] == {
        "group": "deploy-production",
        "cancel-in-progress": False,
    }


def test_a_push_deploys_only_while_the_kill_switch_is_on() -> None:
    """AUTO_DEPLOY is the emergency stop; a manual run is allowed regardless."""
    condition = load("deploy.yml")["jobs"]["plan"]["if"]
    assert "vars.AUTO_DEPLOY == 'true'" in condition
    assert "workflow_dispatch" in condition


def test_the_railway_token_is_only_ever_passed_as_an_environment_variable() -> None:
    """Never inlined into a command, never echoed: it may only appear as `RAILWAY_TOKEN: ${{ secrets... }}`."""
    text = (WORKFLOWS / "deploy.yml").read_text()
    uses = [
        line.strip()
        for line in text.splitlines()
        if "secrets." in line and not line.lstrip().startswith("#")
    ]
    assert uses, "the deploy needs the token"
    assert all(
        line == "RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}" for line in uses
    ), uses
    for script in SCRIPTS.glob("*.sh"):
        body = script.read_text()
        assert not re.search(r"echo[^\n]*\$\{?RAILWAY_TOKEN", body), script.name
        assert "set -x" not in body, f"{script.name}: set -x would print the token"


def test_the_api_goes_first_and_the_web_app_waits_for_it() -> None:
    """A new migration and field are live before the app that uses them."""
    jobs = load("deploy.yml")["jobs"]
    assert jobs["deploy-api"]["needs"] == "plan"
    assert set(jobs["deploy-web"]["needs"]) == {"plan", "deploy-api"}
    assert "needs.deploy-api.result == 'success'" in jobs["deploy-web"]["if"]
    assert "needs.deploy-api.result == 'skipped'" in jobs["deploy-web"]["if"]
    assert (
        "failure" not in jobs["deploy-web"]["if"]
    ), "a failed API deploy must stop the web deploy"
    assert (
        jobs["deploy-api"]["environment"]
        == jobs["deploy-web"]["environment"]
        == "production"
    )


def test_the_gate_names_only_checks_that_exist_and_matches_branch_protection() -> None:
    """A renamed job would make the gate wait forever, so every named check must be a real job."""
    named = load("deploy.yml")["env"]["REQUIRED_CHECKS"].split()
    assert named == ["check", "perf", "visual", "backend-tests"]
    existing: set[str] = set()
    for path in WORKFLOWS.glob("*.yml"):
        existing |= set(load(path.name)["jobs"])
    assert set(named) <= existing, set(named) - existing
    for workflow in ("frontend.yml", "backend-tests.yml"):
        on = load(workflow)["on"]
        assert (
            "pull_request" in on and "push" in on
        ), f"{workflow} must run on PRs and on main"
        assert "paths" not in (
            on.get("pull_request") or {}
        ), f"{workflow} must not be path-filtered"


def test_the_cli_version_is_pinned_exactly() -> None:
    """A floating CLI could change what a deploy does between two merges."""
    assert re.fullmatch(
        r"\d+\.\d+\.\d+", str(load("deploy.yml")["env"]["RAILWAY_CLI_VERSION"])
    )


def test_scripts_are_executable_and_strict() -> None:
    for name in (
        "wait-for-checks.sh",
        "smoke.sh",
        "deploy-service.sh",
        "changed-services.sh",
    ):
        script = SCRIPTS / name
        assert os.access(script, os.X_OK), f"{name} is not executable"
        assert "set -" in script.read_text(), f"{name} should run in strict mode"


def test_the_runbook_documents_the_switches_and_the_deadline() -> None:
    text = (REPO / "RAILWAY_DEPLOYMENT.md").read_text()
    section = text[text.index("## Automatic deploys") :]
    for needle in (
        "AUTO_DEPLOY",
        "RAILWAY_TOKEN",
        "2026-12-01",
        "Run workflow",
        "backend-tests",
    ):
        assert needle in section, needle


# --------------------------------------------------------------------------- behavioural helpers


def fake_bin(tmp_path: Path, name: str, body: str) -> None:
    """Install a fake program named `name` that shadows the real one."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    path = bin_dir / name
    path.write_text(body)
    path.chmod(0o755)


def run(
    tmp_path: Path,
    script: str,
    *args: str,
    env: Optional[dict[str, str]] = None,
    cwd: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    """Run a script with the fake programs first on PATH and a clean, explicit environment."""
    full_env = {
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        **(env or {}),
    }
    return subprocess.run(
        [str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        env=full_env,
        cwd=cwd or tmp_path,
        timeout=60,
    )


# --------------------------------------------------------------------------- wait-for-checks.sh

FAKE_GH = """#!/usr/bin/env bash
# Stands in for `gh api .../check-runs --jq FILTER`: applies FILTER to the canned response.
filter=""
while [ $# -gt 0 ]; do
  if [ "$1" = "--jq" ]; then filter=$2; shift; fi
  shift
done
jq -c "$filter" "$FAKE_CHECK_RUNS"
"""


def check_runs(tmp_path: Path, runs: list[dict]) -> dict[str, str]:
    """Write a canned check-runs response and install the fake gh; return the env to use."""
    fake_bin(tmp_path, "gh", FAKE_GH)
    canned = tmp_path / "runs.json"
    canned.write_text(json.dumps({"check_runs": runs}))
    return {"FAKE_CHECK_RUNS": str(canned), "GITHUB_REPOSITORY": "o/r"}


def cr(
    name: str, conclusion: Optional[str], started: str = "2026-11-03T10:00:00Z"
) -> dict:
    """One check run: finished with `conclusion`, or still running when it is None."""
    return {
        "name": name,
        "status": "completed" if conclusion else "in_progress",
        "conclusion": conclusion,
        "started_at": started,
    }


@needs_tools
def test_the_gate_passes_when_every_required_check_passed(tmp_path: Path) -> None:
    env = check_runs(tmp_path, [cr("check", "success"), cr("perf", "success")])
    done = run(tmp_path, "wait-for-checks.sh", "abc", "0", "check", "perf", env=env)
    assert done.returncode == 0, done.stderr
    assert "all required checks passed" in done.stdout


@needs_tools
def test_the_gate_fails_at_once_when_a_check_failed(tmp_path: Path) -> None:
    env = check_runs(tmp_path, [cr("check", "success"), cr("perf", "failure")])
    done = run(tmp_path, "wait-for-checks.sh", "abc", "0", "check", "perf", env=env)
    assert done.returncode == 1
    assert "FAILED: perf concluded 'failure'" in done.stderr


@needs_tools
@pytest.mark.parametrize("conclusion", ["cancelled", "timed_out", "skipped", "neutral"])
def test_anything_but_success_blocks_a_deploy(tmp_path: Path, conclusion: str) -> None:
    """A skipped or neutral required check is not proof the code was tested."""
    env = check_runs(tmp_path, [cr("check", conclusion)])
    assert (
        run(tmp_path, "wait-for-checks.sh", "abc", "0", "check", env=env).returncode
        == 1
    )


@needs_tools
def test_the_gate_cannot_pass_before_ci_has_started(tmp_path: Path) -> None:
    """No check run yet is "still waiting", never "nothing failed"."""
    env = check_runs(tmp_path, [])
    done = run(tmp_path, "wait-for-checks.sh", "abc", "0", "check", env=env)
    assert done.returncode == 2
    assert "not started" in done.stdout


@needs_tools
def test_the_gate_times_out_while_a_check_is_still_running(tmp_path: Path) -> None:
    env = check_runs(tmp_path, [cr("check", "success"), cr("perf", None)])
    done = run(tmp_path, "wait-for-checks.sh", "abc", "0", "check", "perf", env=env)
    assert done.returncode == 2
    assert "waiting: perf (in_progress)" in done.stdout


@needs_tools
def test_a_rerun_decides_not_the_earlier_failure(tmp_path: Path) -> None:
    """A flaky check that failed and was re-run green counts as green (the latest run wins) ..."""
    runs = [
        cr("perf", "failure", "2026-11-03T10:00:00Z"),
        cr("perf", "success", "2026-11-03T10:30:00Z"),
    ]
    env = check_runs(tmp_path, runs)
    assert (
        run(tmp_path, "wait-for-checks.sh", "abc", "0", "perf", env=env).returncode == 0
    )
    # ... and the reverse: a green run followed by a red re-run is red.
    runs = [
        cr("perf", "success", "2026-11-03T10:00:00Z"),
        cr("perf", "failure", "2026-11-03T10:30:00Z"),
    ]
    env = check_runs(tmp_path, runs)
    assert (
        run(tmp_path, "wait-for-checks.sh", "abc", "0", "perf", env=env).returncode == 1
    )


@needs_tools
def test_the_gate_ignores_checks_it_was_not_asked_about(tmp_path: Path) -> None:
    env = check_runs(
        tmp_path, [cr("check", "success"), cr("backend-docker-build", "failure")]
    )
    assert (
        run(tmp_path, "wait-for-checks.sh", "abc", "0", "check", env=env).returncode
        == 0
    )


@needs_tools
def test_the_gate_refuses_to_run_with_no_checks_named(tmp_path: Path) -> None:
    env = check_runs(tmp_path, [])
    assert run(tmp_path, "wait-for-checks.sh", "abc", "0", env=env).returncode == 64


# --------------------------------------------------------------------------- smoke.sh

FAKE_CURL = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
headers_file = args[args.index("-D") + 1]
body_file = args[args.index("-o") + 1]
url = args[-1]
route = json.loads(os.environ["FAKE_ROUTES"]).get(url, {"status": 404, "headers": [], "body": ""})
open(headers_file, "w").write("HTTP/2 %d\\r\\n" % route["status"] + "".join(h + "\\r\\n" for h in route["headers"]))
open(body_file, "w").write(route["body"])
print(route["status"], end="")
"""

WEB = "https://web.test"
API = "https://api.test"
SECURITY = [
    "strict-transport-security: max-age=31536000",
    "x-content-type-options: nosniff",
    "content-security-policy-report-only: default-src 'self'",
]


def good_web() -> dict:
    return {
        f"{WEB}/login": {
            "status": 200,
            "headers": SECURITY,
            "body": "<h1>Sign in</h1>",
        },
        f"{WEB}/": {
            "status": 200,
            "headers": [],
            "body": "Clone a voice. Hear a sample",
        },
        f"{WEB}/samples/home-sample.wav": {
            "status": 200,
            "headers": ["content-type: audio/wav"],
            "body": "RIFF",
        },
    }


def smoke(tmp_path: Path, target: str, routes: dict) -> subprocess.CompletedProcess:
    fake_bin(tmp_path, "curl", FAKE_CURL)
    env = {
        "FAKE_ROUTES": json.dumps(routes),
        "WEB_URL": WEB,
        "API_URL": API,
        "SMOKE_TRIES": "1",
    }
    return run(tmp_path, "smoke.sh", target, env=env)


@needs_tools
def test_smoke_web_passes_on_a_healthy_site(tmp_path: Path) -> None:
    done = smoke(tmp_path, "web", good_web())
    assert done.returncode == 0, done.stderr
    assert "smoke checks passed" in done.stdout


@needs_tools
@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda r: r[f"{WEB}/login"].update(status=502), "/login answered 502"),
        (
            lambda r: r[f"{WEB}/login"].update(headers=SECURITY[1:]),
            "HSTS header missing",
        ),
        (
            lambda r: r[f"{WEB}/login"].update(headers=[SECURITY[0], SECURITY[2]]),
            "nosniff header missing",
        ),
        (
            lambda r: r[f"{WEB}/login"].update(headers=SECURITY[:2]),
            "CSP header missing",
        ),
        (lambda r: r[f"{WEB}/"].update(body="Welcome"), "home page"),
        (
            lambda r: r[f"{WEB}/samples/home-sample.wav"].update(status=404),
            "sample clip",
        ),
        (
            lambda r: r[f"{WEB}/samples/home-sample.wav"].update(
                headers=["content-type: text/html"]
            ),
            "sample clip",
        ),
    ],
)
def test_smoke_web_names_what_is_broken(tmp_path: Path, mutate, expected: str) -> None:
    routes = good_web()
    mutate(routes)
    done = smoke(tmp_path, "web", routes)
    assert done.returncode == 1
    assert expected in done.stderr


@needs_tools
def test_smoke_api_needs_a_ready_database(tmp_path: Path) -> None:
    ready = {
        "status": 200,
        "headers": [],
        "body": '{"status":"ok","database":{"ok":true}}',
    }
    assert smoke(tmp_path, "api", {f"{API}/health/ready": ready}).returncode == 0
    degraded = {
        "status": 503,
        "headers": [],
        "body": '{"status":"degraded","database":{"ok":false}}',
    }
    done = smoke(tmp_path, "api", {f"{API}/health/ready": degraded})
    assert done.returncode == 1
    assert "database not reachable" in done.stderr


@needs_tools
def test_smoke_rejects_an_unknown_target(tmp_path: Path) -> None:
    assert smoke(tmp_path, "worker", {}).returncode == 64


# --------------------------------------------------------------------------- deploy-service.sh

FAKE_RAILWAY = """#!/usr/bin/env python3
import os, sys
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
if sys.argv[1] == "up":
    sys.exit(int(os.environ.get("FAKE_UP_EXIT", "0")))
print(open(os.environ["FAKE_DEPLOYMENTS"]).read())
"""


def deploy(
    tmp_path: Path, deployments: list[dict], *, token: bool = True, up_exit: int = 0
):
    fake_bin(tmp_path, "railway", FAKE_RAILWAY)
    listing = tmp_path / "deployments.json"
    listing.write_text(json.dumps(deployments))
    env = {
        "FAKE_LOG": str(tmp_path / "railway.log"),
        "FAKE_DEPLOYMENTS": str(listing),
        "FAKE_UP_EXIT": str(up_exit),
        "DEPLOY_TIMEOUT": "0",
    }
    if token:
        env["RAILWAY_TOKEN"] = "not-a-real-token"
    return run(tmp_path, "deploy-service.sh", "web", "abc123", env=env)


def deployment(status: str, message: str = "ci:abc123") -> dict:
    return {"id": "d1", "status": status, "meta": {"cliMessage": message}}


@needs_tools
def test_deploy_uploads_the_commit_tagged_and_succeeds_once_it_is_live(
    tmp_path: Path,
) -> None:
    done = deploy(tmp_path, [deployment("SUCCESS")])
    assert done.returncode == 0, done.stderr
    log = (tmp_path / "railway.log").read_text()
    assert "up --ci --service web --environment production --message ci:abc123" in log
    assert "web is live on abc123" in done.stdout
    assert "not-a-real-token" not in done.stdout + done.stderr


@needs_tools
def test_deploy_finds_its_own_deployment_among_others(tmp_path: Path) -> None:
    """Another commit's deployment, even a failed one, must not decide this one's outcome."""
    others = [
        deployment("FAILED", "ci:other"),
        deployment("SUCCESS", "ci:abc123"),
        deployment("SUCCESS", ""),
    ]
    assert deploy(tmp_path, others).returncode == 0
    mine_failed = [deployment("SUCCESS", "ci:other"), deployment("FAILED", "ci:abc123")]
    assert deploy(tmp_path, mine_failed).returncode == 1


@needs_tools
@pytest.mark.parametrize("status", ["FAILED", "CRASHED", "REMOVED", "SKIPPED"])
def test_deploy_fails_and_says_how_to_go_back_when_it_does_not_go_live(
    tmp_path: Path, status: str
) -> None:
    done = deploy(tmp_path, [deployment(status)])
    assert done.returncode == 1
    assert "keeps the previous version serving" in done.stderr
    assert "AUTO_DEPLOY" in done.stderr


@needs_tools
def test_deploy_times_out_rather_than_waiting_forever(tmp_path: Path) -> None:
    done = deploy(tmp_path, [deployment("BUILDING")])
    assert done.returncode == 2
    assert "timed out" in done.stderr


@needs_tools
def test_deploy_stops_when_the_upload_itself_fails(tmp_path: Path) -> None:
    done = deploy(tmp_path, [deployment("SUCCESS")], up_exit=1)
    assert done.returncode == 1
    assert "keeps the previous version serving" in done.stderr


@needs_tools
def test_deploy_refuses_to_start_without_the_token(tmp_path: Path) -> None:
    done = deploy(tmp_path, [deployment("SUCCESS")], token=False)
    assert done.returncode != 0
    assert "RAILWAY_TOKEN is not set" in done.stderr
    assert not (
        tmp_path / "railway.log"
    ).exists(), "nothing may be uploaded without credentials"


# --------------------------------------------------------------------------- changed-services.sh


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def commit(repo: Path, files: dict[str, str]) -> str:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "c")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    commit(
        path,
        {
            "backend/a.py": "1",
            "frontend/a.ts": "1",
            "railway.toml": "1",
            "README.md": "1",
        },
    )
    return path


def services(repo: Path, before: str, after: str) -> dict[str, str]:
    done = subprocess.run(
        [str(SCRIPTS / "changed-services.sh"), before, after],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return dict(line.split("=") for line in done.stdout.split())


@needs_tools
@pytest.mark.parametrize(
    "changed, api, web",
    [
        ({"backend/b.py": "x"}, "true", "false"),
        ({"backend/alembic/versions/new.py": "x"}, "true", "false"),
        ({"railway.toml": "2"}, "true", "false"),
        ({"frontend/b.tsx": "x"}, "false", "true"),
        ({"frontend/Dockerfile": "x"}, "false", "true"),
        ({"backend/b.py": "x", "frontend/b.tsx": "x"}, "true", "true"),
        ({"README.md": "2"}, "false", "false"),
        ({".github/workflows/x.yml": "x"}, "false", "false"),
        ({"scripts/ci/x.sh": "x"}, "false", "false"),
        ({"RAILWAY_DEPLOYMENT.md": "x"}, "false", "false"),
        ({"docs/backend/notes.md": "x"}, "false", "false"),
        ({"backendish.txt": "x"}, "false", "false"),
    ],
)
def test_each_change_deploys_only_the_services_it_touches(
    repo: Path, changed, api: str, web: str
) -> None:
    before = git(repo, "rev-parse", "HEAD")
    after = commit(repo, changed)
    assert services(repo, before, after) == {"api": api, "web": web}


@needs_tools
def test_a_missing_previous_commit_deploys_everything_so_nothing_is_missed(
    repo: Path,
) -> None:
    head = git(repo, "rev-parse", "HEAD")
    zeros = "0" * 40
    assert services(repo, zeros, head) == {"api": "true", "web": "true"}
    assert services(repo, "f" * 40, head) == {"api": "true", "web": "true"}


@needs_tools
def test_a_merge_of_several_commits_counts_everything_that_changed(repo: Path) -> None:
    before = git(repo, "rev-parse", "HEAD")
    commit(repo, {"backend/b.py": "x"})
    after = commit(repo, {"frontend/b.tsx": "x"})
    assert services(repo, before, after) == {"api": "true", "web": "true"}
