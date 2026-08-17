"""Encrypt/decrypt OAuth and social-media tokens at rest.

Requires TOKEN_ENCRYPTION_KEY (a Fernet key) as a config var. Generate one
locally with:  python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import os
from functools import lru_cache

from cryptography.fernet import Fernet


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = os.environ["TOKEN_ENCRYPTION_KEY"]
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str) -> bytes:
    if value is None:
        return None
    return _fernet().encrypt(value.encode())


def decrypt(value: bytes) -> str:
    if value is None:
        return None
    return _fernet().decrypt(value).decode()
