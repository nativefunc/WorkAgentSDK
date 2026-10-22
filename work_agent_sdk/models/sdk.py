from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Callable
from typing import Any

from work_agent_sdk.core.utils import expand_env as shared_expand_env
from work_agent_sdk.models.base import Model, ModelRequest
from work_agent_sdk.models.errors import ModelError, to_model_error


def expand_env(value: str) -> str:
    try:
        return shared_expand_env(value)
    except LookupError as error:
        raise ModelError(f"缺少配置：{error}", code="auth") from None


async def resolve_setting(value: Any, ctx: Any) -> Any:
    if callable(value):
        value = value(ctx)
        if inspect.isawaitable(value):
            value = await value

    if isinstance(value, str):
        return expand_env(value)
    if isinstance(value, dict):
        return {key: expand_env(item) if isinstance(item, str) else item for key, item in value.items()}
    return value


def to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    return dict(value)


def split_params(body: dict[str, Any], known: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    params = {key: value for key, value in body.items() if key in known}
    extra = {key: value for key, value in body.items() if key not in known}
    return params, extra


class SdkModel(Model):
    """
    通过官方 SDK 调用的模型。api_key 可为字符串（支持 ${环境变量}）或 (ctx) -> str；
    传入 client 时不再接受 api_key 和 base_url。
    """

    default_base_url: str | None = None
    default_api_key: str | None = None

    def __init__(
        self,
        name: str,
        *,
        api_key: str | Callable[..., Any] | None = None,
        base_url: str | None = None,
        headers: dict[str, str] | Callable[..., Any] | None = None,
        timeout: float = 600,
        client: Any = None,
        **options: Any,
    ) -> None:
        super().__init__(name, **options)

        if client is not None and (api_key is not None or base_url is not None):
            raise ValueError("传入 client 时不能再传入 api_key 或 base_url；请在创建 client 时设置")

        self.api_key = api_key if api_key is not None else self.default_api_key
        self.base_url = base_url or self.default_base_url
        self.headers = headers
        self.timeout = timeout
        self.client = client

        # 客户端按 key 创建：key 变化（轮换）时创建新客户端，不再使用旧客户端
        self._client: Any = None
        self._client_key: str | None = None

    def __repr__(self) -> str:
        where = self.base_url or (type(self.client).__name__ if self.client is not None else "默认地址")
        return f"{type(self).__name__}({self.name!r}, {where!r})"

    def new_client(self, api_key: str | None) -> Any:
        """创建 SDK 客户端，并关闭 SDK 自身的重试，由框架统一重试。"""
        raise NotImplementedError

    async def sdk_client(self, request: ModelRequest) -> Any:
        if self.client is not None:
            return self.client

        ctx = request.ctx
        api_key = await resolve_setting(self.api_key, ctx) if self.api_key is not None else None
        if self._client is not None and self._client_key == api_key:
            return self._client

        try:
            client = self.new_client(api_key)
        except ImportError:
            raise
        except Exception as error:
            # 例如未提供 key，且默认环境变量也未设置
            raise ModelError(f"创建 SDK 客户端失败：{error}", code="auth") from error

        self._client, self._client_key = client, api_key
        return client

    async def request_headers(self, request: ModelRequest) -> dict[str, str]:
        headers = await resolve_setting(self.headers, request.ctx) if self.headers is not None else {}
        return {**(headers or {}), **request.settings.extra_headers}

    async def events(self, create: Any, **params: Any) -> AsyncIterator[dict[str, Any]]:
        try:
            stream = await create(**params)
            async for event in stream:
                yield to_dict(event)
        except ModelError:
            raise
        except Exception as error:
            converted = to_model_error(error, self.error_codes)
            if converted is None:
                raise
            raise converted from error


def import_sdk(module: str, package: str) -> Any:
    try:
        return __import__(module)
    except ImportError as error:
        raise ImportError(f"该模型依赖官方 SDK；请执行 pip install {package}") from error
