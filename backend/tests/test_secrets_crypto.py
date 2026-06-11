"""Unit tests for the symmetric encryption used by settings_store."""

import pytest
from cryptography.fernet import InvalidToken

from services import secrets_crypto


@pytest.fixture
def stable_jwt_secret(monkeypatch):
    monkeypatch.setattr(
        secrets_crypto.config.settings,
        "jwt_secret",
        "x" * 32,
    )


def test_encrypt_then_decrypt_roundtrip(stable_jwt_secret):
    plaintext = "super-secret-couchbase-password"
    token = secrets_crypto.encrypt(plaintext)
    assert token.startswith(secrets_crypto.ENCRYPTED_PREFIX)
    assert plaintext not in token  # ciphertext must hide the plaintext
    assert secrets_crypto.decrypt(token) == plaintext


def test_decrypt_passes_through_legacy_plaintext(stable_jwt_secret):
    """Values without the prefix are treated as pre-encryption legacy data."""
    legacy = "legacy-plaintext-password"
    assert secrets_crypto.decrypt(legacy) == legacy


def test_encrypt_empty_string_returns_empty(stable_jwt_secret):
    assert secrets_crypto.encrypt("") == ""
    assert secrets_crypto.decrypt("") == ""


def test_decrypt_with_rotated_key_raises(monkeypatch):
    monkeypatch.setattr(secrets_crypto.config.settings, "jwt_secret", "k1" * 16)
    token = secrets_crypto.encrypt("payload")

    monkeypatch.setattr(secrets_crypto.config.settings, "jwt_secret", "k2" * 16)
    with pytest.raises(InvalidToken):
        secrets_crypto.decrypt(token)


def test_encrypt_is_non_deterministic(stable_jwt_secret):
    """Fernet uses a random IV → same plaintext encrypts to different tokens."""
    a = secrets_crypto.encrypt("same-plaintext")
    b = secrets_crypto.encrypt("same-plaintext")
    assert a != b
    assert secrets_crypto.decrypt(a) == "same-plaintext"
    assert secrets_crypto.decrypt(b) == "same-plaintext"
