"""Write a single known user to ``$APP_USERS_FILE`` for Playwright E2E runs.

The user has ``must_change_password=False`` so the smoke test can go straight
from login to the chat page without detouring through the forced-rotation
flow. ``APP_USERS_FILE`` must be set (the webServer config in
``frontend/playwright.config.ts`` points it at a tmp path so developer
``backend/data/app_users.json`` is never touched).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.user_store import USERS_FILE, hash_password  # noqa: E402

DEFAULT_USERNAME = "e2e"
DEFAULT_PASSWORD = "e2e-password-1234"


def main() -> int:
    if USERS_FILE.endswith("backend/data/app_users.json"):
        print(
            "refusing to overwrite backend/data/app_users.json — "
            "set APP_USERS_FILE to a tmp path first",
            file=sys.stderr,
        )
        return 1
    username = os.environ.get("E2E_USERNAME", DEFAULT_USERNAME)
    password = os.environ.get("E2E_PASSWORD", DEFAULT_PASSWORD)

    os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
    payload = {
        "users": [
            {
                "username": username,
                "password_hash": hash_password(password),
                "must_change_password": False,
            }
        ]
    }
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    print(f"Seeded {username} into {USERS_FILE}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
