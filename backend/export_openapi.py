"""Export the API's OpenAPI schema for the frontend contract tests.

    python -m backend.export_openapi          # rewrite frontend/contract/openapi.json
    python -m backend.export_openapi --check  # exit 1 if the committed file is stale

The frontend validates its mocks against this snapshot; a backend test runs the
same check so a schema change cannot land without refreshing the snapshot.
"""

import argparse
import json
import sys
from pathlib import Path

from backend.main import app

SNAPSHOT_PATH = (
    Path(__file__).resolve().parent.parent / "frontend" / "contract" / "openapi.json"
)


def render_schema() -> str:
    """Return the app's OpenAPI schema as stable, sorted, newline-terminated JSON."""
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write the snapshot, or with ``--check`` compare it; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="fail if the snapshot is stale"
    )
    args = parser.parse_args(argv)
    rendered = render_schema()
    if args.check:
        current = SNAPSHOT_PATH.read_text() if SNAPSHOT_PATH.exists() else ""
        if current != rendered:
            sys.stderr.write(
                "frontend/contract/openapi.json is stale; run export_openapi.\n"
            )
            return 1
        return 0
    SNAPSHOT_PATH.write_text(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
