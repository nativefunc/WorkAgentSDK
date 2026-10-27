from __future__ import annotations

import base64
import hashlib

from work_agent_sdk.core.utils import maybe_env


class KeyProvider:
    """Key used for encryption. To integrate a KMS, subclass this and implement encrypt and decrypt."""

    def encrypt(self, data: bytes) -> bytes:
        raise NotImplementedError

    def decrypt(self, data: bytes) -> bytes:
        raise NotImplementedError


MIN_SECRET_LENGTH = 32


class LocalKey(KeyProvider):
    # The key is derived with a single SHA-256, so it can't be a passphrase; it must be a random string of at least 32 characters

    def __init__(self, secret: str) -> None:
        from work_agent_sdk.core.errors import ConfigError

        try:
            from cryptography.fernet import Fernet
        except ImportError as error:  # pragma: no cover
            raise ConfigError("secret_key requires cryptography; run pip install cryptography") from error

        value = maybe_env(secret)
        if len(value) < MIN_SECRET_LENGTH:
            raise ConfigError(f"secret_key is too short ({len(value)} characters; at least {MIN_SECRET_LENGTH} required)")

        digest = hashlib.sha256(value.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, data: bytes) -> bytes:
        return self._fernet.encrypt(data)

    def decrypt(self, data: bytes) -> bytes:
        return self._fernet.decrypt(data)


def key_provider(secret_key: str | KeyProvider | None) -> KeyProvider | None:
    if secret_key is None or isinstance(secret_key, KeyProvider):
        return secret_key
    return LocalKey(secret_key)
