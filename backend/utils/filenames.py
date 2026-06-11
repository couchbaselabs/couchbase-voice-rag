"""Filename sanitization helpers.

Incoming user-provided filenames reach paths, document IDs, and N1QL
parameters. Callers must route names through `safe_filename()` before
any further use to defend against path traversal and injection.
"""

from __future__ import annotations

import re
import unicodedata

_MAX_LENGTH = 200
_ALLOWED_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def safe_filename(name: str) -> str:
    """Return a sanitized filename suitable for storage keys and document IDs.

    Behavior:
    - Unicode NFC normalization so visually identical characters collapse.
    - Any character outside `[A-Za-z0-9._-]` is replaced with `_`.
    - Leading dots (hidden files / ``..``) are stripped so path traversal
      fragments cannot survive.
    - Length is capped at 200 characters.

    Raises:
        ValueError: when the sanitized result is empty.
    """
    if name is None:
        raise ValueError("filename is required")

    normalized = unicodedata.normalize("NFC", name).strip()
    # Keep only the basename; callers should never pass full paths, but be defensive.
    normalized = normalized.replace("\\", "/").split("/")[-1]
    # Replace disallowed chars
    sanitized = _ALLOWED_CHARS.sub("_", normalized)
    # Strip leading dots to kill ``..`` and hidden-file sequences
    sanitized = sanitized.lstrip(".")

    if len(sanitized) > _MAX_LENGTH:
        # Preserve the extension when truncating
        stem, dot, ext = sanitized.rpartition(".")
        if dot and len(ext) <= 10:
            keep = _MAX_LENGTH - len(ext) - 1
            sanitized = stem[:keep] + "." + ext
        else:
            sanitized = sanitized[:_MAX_LENGTH]

    if not sanitized:
        raise ValueError("filename is empty after sanitization")

    return sanitized
