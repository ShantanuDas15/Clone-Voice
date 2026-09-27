"""Validation for HARDENING_PLAN.md finding P2-L9: transitive dependencies
must be pinned by hash in backend/requirements.lock.txt, and torch (which
has its own CPU/CUDA index story, see P2-H3) must never appear in it.
"""

import re
import subprocess

from backend.relock_requirements import _strip_torch_block

REPO_ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()


def _read(path: str) -> str:
    with open(f"{REPO_ROOT}/{path}", encoding="utf-8") as f:
        return f.read()


def _read_lines(path: str) -> list:
    with open(f"{REPO_ROOT}/{path}", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def _normalize(name: str) -> str:
    """PEP 503 name normalization: '_', '.' and '-' are equivalent, so
    `huggingface_hub` (requirements.txt) and `huggingface-hub` (the lock
    file, uv's own normalized spelling) must compare equal."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _direct_package_names() -> set:
    """Package names declared in requirements.txt, normalized, no version."""
    names = set()
    for line in _read_lines("backend/requirements.txt"):
        match = re.match(r"^([A-Za-z0-9_.-]+)", line)
        if match:
            names.add(_normalize(match.group(1)))
    return names


def _lock_package_names() -> set:
    """Package names pinned in requirements.lock.txt, normalized."""
    lock = _read("backend/requirements.lock.txt")
    return {
        _normalize(name)
        for name in re.findall(r"^([A-Za-z0-9_.-]+)==", lock, re.MULTILINE)
    }


def test_lock_file_has_no_torch_entry() -> None:
    """torch is deliberately excluded — it only ships a CUDA build on the
    default index; a hash-locked entry for it would fight the CPU-index
    install the Dockerfile does separately (see the lock file's header)."""
    lock = _read("backend/requirements.lock.txt")
    assert not re.search(r"^torch==", lock, re.MULTILINE)


def test_lock_file_documents_the_torch_exclusion_and_regeneration_command() -> None:
    lock = _read("backend/requirements.lock.txt")
    assert "P2-L9" in lock
    assert "backend.relock_requirements" in lock


def test_lock_file_pins_every_direct_dependency_except_torch() -> None:
    direct = _direct_package_names() - {"torch"}
    locked = _lock_package_names()
    missing = direct - locked
    assert not missing, f"requirements.txt packages missing from the lock: {missing}"


def test_every_locked_package_has_at_least_one_hash() -> None:
    lock = _read("backend/requirements.lock.txt")
    # Split on package header lines (name==version, optionally continued with `\`).
    blocks = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", lock)
    package_blocks = [b for b in blocks if re.match(r"^[A-Za-z0-9_.-]+==", b)]
    assert len(package_blocks) > 50  # sanity: this is a real, populated lock
    for block in package_blocks:
        name = block.split("==", 1)[0]
        assert "--hash=sha256:" in block, f"{name} has no hash in the lock file"


def test_dockerfile_requires_hashes_on_the_locked_install() -> None:
    dockerfile = _read("backend/Dockerfile")
    assert re.search(
        r"pip install --no-cache-dir --require-hashes -r /tmp/requirements\.lock\.txt",
        dockerfile,
    )


def test_dockerfile_copies_the_lock_file() -> None:
    dockerfile = _read("backend/Dockerfile")
    assert "COPY backend/requirements.lock.txt /tmp/requirements.lock.txt" in dockerfile


def test_strip_torch_block_removes_only_the_torch_entry() -> None:
    """Unit-tests relock_requirements.py's block-stripping logic directly,
    without invoking uv or the network."""
    sample = (
        "sympy==1.14.0 \\\n"
        "    --hash=sha256:aaa\n"
        "    # via torch\n"
        "torch==2.13.0+cpu \\\n"
        "    --hash=sha256:bbb \\\n"
        "    --hash=sha256:ccc\n"
        "    # via\n"
        "    #   -r requirements.txt\n"
        "    #   resemblyzer\n"
        "tqdm==4.70.1 \\\n"
        "    --hash=sha256:ddd\n"
    )
    result = _strip_torch_block(sample)
    assert "torch==" not in result
    assert "sympy==1.14.0" in result
    assert "tqdm==4.70.1" in result
    # Nothing from torch's own continuation/`# via` lines should leak through
    # onto tqdm's block.
    assert "resemblyzer" not in result


def test_strip_torch_block_is_a_no_op_without_torch() -> None:
    sample = "numpy==1.26.4 \\\n    --hash=sha256:aaa\n    # via -r requirements.txt\n"
    assert _strip_torch_block(sample) == sample


def test_constraints_file_pins_match_the_lock_file() -> None:
    """Regression guard for the two resolver footguns documented in
    requirements.constraints.txt: if either drifts from what's actually
    pinned in the lock, the constraint stopped doing its job."""
    constraints = _read_lines("backend/requirements.constraints.txt")
    lock = _read("backend/requirements.lock.txt")
    for line in constraints:
        assert line in lock, f"constraint {line!r} not reflected in the lock file"


def test_requirements_dev_includes_uv_for_relocking() -> None:
    lines = _read_lines("backend/requirements-dev.txt")
    assert any(line.lower().startswith("uv==") for line in lines)


def test_backend_audit_workflow_also_scans_the_lock_file() -> None:
    """P2-L9: the pip-audit gate must cover the full transitive tree, not
    just the direct pins in requirements.txt."""
    workflow = _read(".github/workflows/backend-audit.yml")
    assert "backend/requirements.lock.txt" in workflow
    assert "--ignore-vuln PYSEC-2026-3447" in workflow


def test_docker_workflow_rebuilds_on_lock_file_changes() -> None:
    workflow = _read(".github/workflows/docker-build.yml")
    assert '"backend/requirements.lock.txt"' in workflow
    assert '"backend/requirements.constraints.txt"' in workflow
