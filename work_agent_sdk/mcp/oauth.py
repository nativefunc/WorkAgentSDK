from __future__ import annotations

import ipaddress
import json
import logging
import time
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from work_agent_sdk.core.secrets import KeyProvider
from work_agent_sdk.mcp.store import MCPTokenStore

logger = logging.getLogger("work_agent_sdk")

GRANT_TYPES = ["authorization_code", "refresh_token"]


class AuthRequired(Exception): ...


def find_error(error: BaseException | None, kind: type | tuple[type, ...]) -> BaseException | None:
    # mcp 客户端的错误常被包在 TaskGroup 的异常组里
    visited: set[int] = set()
    stack: list[BaseException | None] = [error]
    while stack:
        current = stack.pop()
        if current is None or id(current) in visited:
            continue

        visited.add(id(current))

        if isinstance(current, kind):
            return current

        stack.extend(getattr(current, "exceptions", None) or [])
        stack.append(current.__cause__)
        stack.append(current.__context__)

    return None


def origin_of(url: str) -> str:
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def is_secure_url(url: str) -> bool:
    parts = urlparse(url)
    if parts.scheme == "https":
        return True
    if parts.scheme != "http" or not parts.hostname:
        return False
    if parts.hostname == "localhost":
        return True

    try:
        return ipaddress.ip_address(parts.hostname).is_loopback
    except ValueError:
        return False


class OAuth(BaseModel):
    """MCP 服务的 OAuth 配置。授权地址必须为 https，且与 MCP 服务同域，或列于 trusted_origins 中。"""

    model_config = ConfigDict(extra="forbid")

    redirect_uri: str
    scopes: list[str] = Field(default_factory=list)
    client_id: str | None = None
    client_secret: str | None = None
    client_name: str = "work-agent-sdk"
    trusted_origins: list[str] = Field(default_factory=list)
    state_ttl: float = 600

    @field_validator("trusted_origins")
    @classmethod
    def _origins(cls, value: list[str]) -> list[str]:
        return [origin.rstrip("/").lower() for origin in value]

    def allowed_origins(self, server_url: str) -> set[str]:
        return {origin_of(server_url), *self.trusted_origins}

    def check_authorization_url(self, server_name: str, server_url: str, url: str) -> None:
        if not is_secure_url(url):
            raise AuthRequired(f"授权地址不是 https，已拒绝：{origin_of(url)}")
        if origin_of(url) not in self.allowed_origins(server_url):
            raise AuthRequired(
                f"授权地址的域名 {origin_of(url)} 不在信任列表中，已拒绝；"
                f"如果该地址确为 {server_name} 的授权服务，请将其加入 OAuth(trusted_origins=[...])"
            )

    def client_metadata(self) -> Any:
        from mcp.shared.auth import OAuthClientMetadata

        return OAuthClientMetadata(
            client_name=self.client_name,
            redirect_uris=[self.redirect_uri],
            grant_types=GRANT_TYPES,
            response_types=["code"],
            scope=" ".join(self.scopes) or None,
            token_endpoint_auth_method="client_secret_post" if self.client_secret else "none",
        )

    def known_client(self) -> Any:
        """开发者提供了 client_id 时直接使用，不进行动态注册。"""
        if not self.client_id:
            return None

        from mcp.shared.auth import OAuthClientInformationFull

        return OAuthClientInformationFull(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uris=[self.redirect_uri],
            client_name=self.client_name,
            grant_types=GRANT_TYPES,
            response_types=["code"],
            token_endpoint_auth_method="client_secret_post" if self.client_secret else "none",
            scope=" ".join(self.scopes) or None,
        )


class TokenRecords:
    # 密文包含记录名，解密后核对，防止记录被调换

    def __init__(self, store: MCPTokenStore, key: KeyProvider | None) -> None:
        self.store = store
        self.key = key
        self._memory: dict[str, dict[str, Any]] = {}
        self._warned = False

    async def load(self, name: str) -> dict[str, Any]:
        if self.key is None:
            return dict(self._memory.get(name, {}))

        stored = await self.store.get(name)
        if not stored:
            return {}

        try:
            plain = json.loads(self.key.decrypt(stored))
            if plain.get("name") != name:
                raise ValueError("记录名不一致")
            return dict(plain["record"])
        except Exception as error:
            logger.warning("无法读取 MCP 令牌 记录 %s（%s）；需重新授权", name, type(error).__name__)
            return {}

    async def save(self, name: str, record: dict[str, Any]) -> None:
        if self.key is None:
            if not self._warned:
                logger.warning("Runner 未配置 secret_key：MCP 服务的 token 仅保存在内存中，后端重启后需重新授权")
                self._warned = True
            self._memory[name] = dict(record)
            return
        plain = json.dumps({"name": name, "record": record}, ensure_ascii=False).encode()
        await self.store.put(name, self.key.encrypt(plain))

    async def delete(self, name: str) -> None:
        self._memory.pop(name, None)
        if self.key is not None:
            await self.store.delete(name)


class TokenStorage:
    def __init__(self, records: TokenRecords, server_name: str, server_url: str, *, hide_tokens: bool = False) -> None:
        self.records = records
        self.name = f"mcp_oauth:{server_name}:{server_url}"
        self.hide_tokens = hide_tokens
        self.context: Any = None

    async def load(self) -> dict[str, Any]:
        return await self.records.load(self.name)

    async def save(self, record: dict[str, Any]) -> None:
        await self.records.save(self.name, record)

    async def get_tokens(self) -> Any:
        from mcp.shared.auth import OAuthToken

        if self.hide_tokens:
            return None

        tokens = (await self.load()).get("tokens")
        return OAuthToken.model_validate(tokens) if tokens else None

    async def set_tokens(self, tokens: Any) -> None:
        record = await self.load()
        record["tokens"] = tokens.model_dump(mode="json", exclude_none=True)
        record["saved_at"] = time.time()
        metadata = getattr(self.context, "oauth_metadata", None)
        if metadata is not None:
            record["server_metadata"] = metadata.model_dump(mode="json", exclude_none=True)
            record["auth_server_url"] = self.context.auth_server_url

        await self.save(record)
        self.hide_tokens = False

    async def get_client_info(self) -> Any:
        from mcp.shared.auth import OAuthClientInformationFull

        client = (await self.load()).get("client")
        return OAuthClientInformationFull.model_validate(client) if client else None

    async def set_client_info(self, client_info: Any) -> None:
        record = await self.load()
        record["client"] = client_info.model_dump(mode="json", exclude_none=True)
        await self.save(record)

    async def server_metadata(self) -> tuple[Any, str | None]:
        from mcp.shared.auth import OAuthMetadata

        record = await self.load()
        metadata = record.get("server_metadata")
        return (OAuthMetadata.model_validate(metadata) if metadata else None), record.get("auth_server_url")

    async def token_expiry(self) -> float | None:
        record = await self.load()
        tokens = record.get("tokens") or {}
        if tokens.get("expires_in") is None or record.get("saved_at") is None:
            return None
        return float(record["saved_at"]) + float(tokens["expires_in"])

    async def has_tokens(self) -> bool:
        return bool((await self.load()).get("tokens"))

    async def forget_tokens(self) -> None:
        record = await self.load()
        if record.pop("tokens", None) is not None:
            await self.save(record)

    async def clear(self) -> None:
        await self.records.delete(self.name)


def build_provider(
    oauth: OAuth,
    server_name: str,
    server_url: str,
    storage: TokenStorage,
    *,
    redirect_handler: Any,
    callback_handler: Any,
) -> Any:
    from mcp.client.auth import OAuthClientProvider

    class Provider(OAuthClientProvider):
        async def _initialize(self) -> None:
            await super()._initialize()
            expiry = await storage.token_expiry()
            if expiry is not None:
                self.context.token_expiry_time = expiry

            if self.context.oauth_metadata is None:
                metadata, auth_server_url = await storage.server_metadata()
                self.context.oauth_metadata = metadata
                self.context.auth_server_url = self.context.auth_server_url or auth_server_url

    provider = Provider(
        server_url,
        oauth.client_metadata(),
        storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )
    storage.context = provider.context
    return provider


async def revoke_tokens(oauth: OAuth, server_url: str, storage: TokenStorage) -> bool:
    import httpx2

    record = await storage.load()
    tokens = record.get("tokens") or {}
    client = record.get("client") or {}
    if not tokens or not client.get("client_id"):
        return False

    endpoint = (record.get("server_metadata") or {}).get("revocation_endpoint")
    if not endpoint or not is_secure_url(endpoint) or origin_of(endpoint) not in oauth.allowed_origins(server_url):
        return False

    revoked = False
    async with httpx2.AsyncClient(timeout=10) as http:
        for token_type in ("refresh_token", "access_token"):
            if not tokens.get(token_type):
                continue

            form = {
                "token": tokens[token_type],
                "token_type_hint": token_type,
                "client_id": client["client_id"],
            }
            if client.get("client_secret"):
                form["client_secret"] = client["client_secret"]

            try:
                response = await http.post(endpoint, data=form)
                revoked = revoked or response.status_code == 200
            except Exception as error:
                logger.warning("撤销授权失败：%s", type(error).__name__)

    return revoked
