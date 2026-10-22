from __future__ import annotations

import base64
import hashlib

from work_agent_sdk.core.utils import maybe_env


class KeyProvider:
    """加密所用的密钥。接入 KMS 时继承此类并实现 encrypt 与 decrypt。"""

    def encrypt(self, data: bytes) -> bytes:
        raise NotImplementedError

    def decrypt(self, data: bytes) -> bytes:
        raise NotImplementedError


MIN_SECRET_LENGTH = 32


class LocalKey(KeyProvider):
    # 密钥只经一次 SHA-256 派生，不能用口令，须为不少于 32 个字符的随机串

    def __init__(self, secret: str) -> None:
        from work_agent_sdk.core.errors import ConfigError

        try:
            from cryptography.fernet import Fernet
        except ImportError as error:  # pragma: no cover
            raise ConfigError("使用 secret_key 需要 cryptography；请执行 pip install cryptography") from error

        value = maybe_env(secret)
        if len(value) < MIN_SECRET_LENGTH:
            raise ConfigError(f"secret_key 过短（{len(value)} 个字符，至少需要 {MIN_SECRET_LENGTH} 个）")

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
