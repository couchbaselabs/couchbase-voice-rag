"""Dump the FastAPI schema to ``backend/openapi.json``.

Run from ``backend/`` as ``uv run python scripts/dump_openapi.py``.

The frontend's ``generate-api`` script reads the written file to produce
``frontend/src/types/api.d.ts``. CI re-runs this script and uses
``git diff --exit-code backend/openapi.json`` to refuse PRs that changed
the schema without regenerating the checked-in snapshot.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from main import app  # noqa: E402


def main() -> int:
    schema = app.openapi()
    serialized = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    out = BACKEND_DIR / "openapi.json"
    out.write_text(serialized, encoding="utf-8")
    print(f"Wrote {out.relative_to(BACKEND_DIR.parent)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
