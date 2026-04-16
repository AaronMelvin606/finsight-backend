"""
Fernet encryption utilities for Xero OAuth tokens at rest.

Migration strategy:
    Existing plaintext tokens in production do NOT need a bulk data migration.
    The is_encrypted() guard on every read means:
      - If a stored token starts with "gAAA" (Fernet prefix), it is decrypted.
      - If it does not, it is treated as plaintext and used as-is.
    On the next Xero token refresh or reconnect, the new token from Xero is
    stored encrypted. This gives a zero-downtime rolling migration — every
    org migrates automatically on their next token refresh cycle (max 30 min).
"""

import os

from cryptography.fernet import Fernet


def get_fernet() -> Fernet:
    key = os.getenv("XERO_TOKEN_ENCRYPTION_KEY")
    if not key:
        raise ValueError("XERO_TOKEN_ENCRYPTION_KEY env var not set")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(token: str) -> str:
    """Encrypt a plaintext token for storage."""
    return get_fernet().encrypt(token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a Fernet-encrypted token."""
    return get_fernet().decrypt(encrypted_token.encode()).decode()


def is_encrypted(value: str) -> bool:
    """Check if a token value is already Fernet-encrypted."""
    return value.startswith("gAAA")


def safe_decrypt(value: str) -> str:
    """Decrypt if encrypted, otherwise return as-is (handles legacy plaintext)."""
    if is_encrypted(value):
        return decrypt_token(value)
    return value
