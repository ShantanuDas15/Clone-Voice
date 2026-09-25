"""Static validation for HARDENING_PLAN.md finding L7: dev/test tooling
(pytest, black, isort) must not ship in the runtime `requirements.txt`, and
`bcrypt` must be exact-pinned rather than range-pinned.
"""

import subprocess

REPO_ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()

DEV_ONLY_PACKAGES = ("pytest", "pytest-asyncio", "black", "isort")


def _read_lines(path: str) -> list:
    with open(f"{REPO_ROOT}/{path}", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def test_runtime_requirements_excludes_dev_tools() -> None:
    lines = _read_lines("backend/requirements.txt")
    for package in DEV_ONLY_PACKAGES:
        assert not any(
            line.lower().startswith(package.lower()) for line in lines
        ), f"{package} must not be in the runtime requirements.txt (finding L7)"


def test_runtime_requirements_pins_bcrypt_exactly() -> None:
    lines = _read_lines("backend/requirements.txt")
    bcrypt_lines = [line for line in lines if line.lower().startswith("bcrypt")]

    assert bcrypt_lines == ["bcrypt==3.2.2"]


def test_dev_requirements_file_exists_and_includes_dev_tools() -> None:
    lines = _read_lines("backend/requirements-dev.txt")
    for package in DEV_ONLY_PACKAGES:
        assert any(
            line.lower().startswith(package.lower()) for line in lines
        ), f"{package} must be listed in requirements-dev.txt"


def test_dev_requirements_pulls_in_runtime_requirements() -> None:
    lines = _read_lines("backend/requirements-dev.txt")

    assert "-r requirements.txt" in lines


def test_dockerfile_only_installs_runtime_requirements() -> None:
    dockerfile = _read_lines("backend/Dockerfile")
    install_lines = [line for line in dockerfile if "pip install" in line]

    # Two steps since P2-H3: torch alone from the CPU index, then everything.
    assert len(install_lines) == 2
    assert not any("requirements-dev.txt" in line for line in install_lines)
    assert sum("-r /tmp/requirements.txt" in line for line in install_lines) == 1
