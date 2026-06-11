"""Symmetric encryption for secret fields persisted in ``data/db_settings.json``.

The Settings UI captures secrets that the backend later needs in
plaintext at runtime (Couchbase passwords, the Azure OpenAI API key),
so they have to live in a reversible, symmetrically-encrypted form on
disk. The encryption key is derived from ``JWT_SECRET`` via HKDF-SHA256
so operators only manage one secret — when ``JWT_SECRET`` is rotated,
saved settings become unreadable on purpose.

Wire format:
    enc:v1:<urlsafe-base64 Fernet token>

Values that don't begin with ``ENCRYPTED_PREFIX`` are returned verbatim
on decrypt — this preserves backward compatibility with saved files
written before this module existed (legacy plaintext).
"""

import base64
import logging

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import config

logger = logging.getLogger(__name__)

ENCRYPTED_PREFIX = "enc:v1:"
_HKDF_INFO = b"couchbase-realtime-rag/settings-encryption/v1"


def _derive_key() -> bytes:
    secret = config.settings.jwt_secret.encode("utf-8")
    if not secret:
        raise RuntimeError(
            "JWT_SECRET unavailable for settings encryption key derivation"
        )
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_HKDF_INFO,
    ).derive(secret)
    return base64.urlsafe_b64encode(derived)


def encrypt(plaintext: str) -> str:
    """Return a Fernet token (with ``enc:v1:`` prefix) for ``plaintext``.

    Empty input is passed through so the caller doesn't have to special-case
    blank settings fields.
    """
    if not plaintext:
        return ""
    token = Fernet(_derive_key()).encrypt(plaintext.encode("utf-8"))
    return ENCRYPTED_PREFIX + token.decode("ascii")


def decrypt(value: str) -> str:
    """Return the plaintext for ``value``.

    Values without the ``enc:v1:`` prefix are treated as legacy plaintext
    and returned unchanged. Values with the prefix that fail to decrypt
    (e.g. JWT_SECRET rotated) raise ``InvalidToken`` — callers decide
    whether to drop the saved settings or surface the error.
    """
    if not value:
        return ""
    if not value.startswith(ENCRYPTED_PREFIX):
        return value
    token = value[len(ENCRYPTED_PREFIX) :].encode("ascii")
    return Fernet(_derive_key()).decrypt(token).decode("utf-8")


__all__ = ["ENCRYPTED_PREFIX", "InvalidToken", "encrypt", "decrypt"]
