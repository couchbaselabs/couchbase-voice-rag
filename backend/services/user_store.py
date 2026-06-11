import json
import os

import bcrypt

USERS_FILE = os.environ.get(
    "APP_USERS_FILE",
    os.path.join(os.path.dirname(__file__), "..", "data", "app_users.json"),
)


def _load_raw() -> list[dict]:
    try:
        with open(USERS_FILE) as f:
            data = json.load(f)
            return data.get("users", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_raw(users: list[dict]):
    os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
    with open(USERS_FILE, "w") as f:
        json.dump({"users": users}, f)


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of ``plain``."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def get_user(username: str) -> dict | None:
    """Return the stored user record for ``username`` or ``None`` if absent."""
    for user in _load_raw():
        if user.get("username") == username:
            return user
    return None


def verify_password(username: str, password: str) -> bool:
    """Constant-time bcrypt compare of ``password`` against the stored hash."""
    user = get_user(username)
    if not user:
        return False
    stored_hash = user.get("password_hash", "")
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except ValueError:
        return False


def must_change_password(username: str) -> bool:
    """Whether ``username`` must rotate the password before normal use."""
    user = get_user(username)
    if not user:
        return False
    return bool(user.get("must_change_password", False))


def set_password(username: str, new_password: str):
    """Store a new bcrypt hash for ``username`` and clear the rotation flag."""
    users = _load_raw()
    for user in users:
        if user.get("username") == username:
            user["password_hash"] = hash_password(new_password)
            user["must_change_password"] = False
            break
    else:
        users.append({
            "username": username,
            "password_hash": hash_password(new_password),
            "must_change_password": False,
        })
    _save_raw(users)


def seed_from_plain(plain_users: dict[str, str]) -> int:
    """Seed app_users.json from a plain username:password mapping.
    Seeded users get must_change_password=True so the first login prompts a change.
    Returns number of users seeded (0 if file already has users).
    """
    if _load_raw():
        return 0
    users = [
        {
            "username": username,
            "password_hash": hash_password(password),
            "must_change_password": True,
        }
        for username, password in plain_users.items()
    ]
    _save_raw(users)
    return len(users)
