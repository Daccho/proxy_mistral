"""Symmetric encryption for sensitive data at rest.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the already-installed
``cryptography`` package.  The encryption key is derived from
PROXY_MISTRAL_API_KEY via PBKDF2 so no extra secret is needed.

Addresses: OWASP A02 (Cryptographic Failures)
"""

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

_SALT = b"proxy-mistral-token-encryption"


def _get_fernet() -> Fernet:
    secret = os.getenv("PROXY_MISTRAL_API_KEY", "default-dev-key")
    key = hashlib.pbkdf2_hmac("sha256", secret.encode(), _SALT, 100_000)
    return Fernet(base64.urlsafe_b64encode(key[:32]))


def encrypt_data(plaintext: str) -> str:
    """Encrypt a string and return base64-encoded ciphertext."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_data(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext string.

    Raises ``cryptography.fernet.InvalidToken`` on failure.
    """
    return _get_fernet().decrypt(ciphertext.encode()).decode()
