from __future__ import annotations

import email.utils
import random
import socket
import ssl
import sys
import time
from collections.abc import Iterable, Mapping
from typing import Any

RETRYABLE_CODES = {"rate_limit", "overloaded", "server", "network", "timeout"}


class ModelError(Exception):
    """模型调用失败。code 为错误类别（auth、rate_limit、context_overflow 等），可重试的错误由框架退避重试。"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "unknown",
        retry_after: float | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retry_after = retry_after
        self.status = status

    def __repr__(self) -> str:
        return f"ModelError({self.code}: {self.message[:200]})"

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_CODES


def error_fields(body: Any) -> tuple[list[str], str, int | None]:
    if not isinstance(body, dict):
        return [], str(body or ""), None

    inner = body["error"] if isinstance(body.get("error"), dict) else body
    codes, status = [], None
    for key in ("code", "type"):
        value = inner.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            status = value
        elif isinstance(value, str) and value:
            codes.append(value)

    return codes, str(inner.get("message") or ""), status


def classify(status: int | None, codes: Iterable[str], known: Mapping[str, str]) -> str:
    # 只按错误码和状态码归类，不看错误信息的文字；分层错误码先查完整的，再逐级查上级
    for code in codes:
        parts = code.split(".") if code else []
        for end in range(len(parts), 0, -1):
            found = known.get(".".join(parts[:end]))
            if found:
                return found

    return classify_status(status)


def classify_status(status: int | None) -> str:
    if status is None or status < 400:
        return "unknown"
    if status in (401, 403):
        return "auth"
    if status == 402:
        return "quota"
    if status == 429:
        return "rate_limit"
    if status in (408, 504):
        return "timeout"
    if status in (503, 529):
        return "overloaded"
    if status >= 500:
        return "server"
    return "bad_request"


def retry_after(headers: Any) -> float | None:
    if not headers:
        return None

    try:
        milliseconds = headers.get("retry-after-ms")
        value = headers.get("retry-after")
    except Exception:
        return None

    if milliseconds:
        return max(0.0, float(milliseconds) / 1000)
    if not value:
        return None

    try:
        return max(0.0, float(value))
    except ValueError:
        pass

    try:
        moment = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None

    return max(0.0, moment.timestamp() - time.time())


def _loaded(*names: str) -> tuple[type[BaseException], ...]:
    # 没导入的库不可能抛出它的异常，不必为此导入
    found = []
    for name in names:
        module_name, _, class_name = name.rpartition(".")
        module = sys.modules.get(module_name)
        cls = getattr(module, class_name, None) if module is not None else None
        if isinstance(cls, type) and issubclass(cls, BaseException):
            found.append(cls)

    return tuple(found)


SDKS = ("openai", "anthropic")
HTTP_LIBRARIES = ("httpx", "httpx2")


def to_model_error(error: BaseException, known: Mapping[str, str]) -> ModelError | None:
    if isinstance(error, ModelError):
        return error

    text = f"{type(error).__name__}: {error}"

    # 超时先于连接错误判断：SDK 与 httpx 的超时异常均为连接错误的子类
    timeouts = _loaded(
        *(f"{sdk}.APITimeoutError" for sdk in SDKS),
        *(f"{lib}.TimeoutException" for lib in HTTP_LIBRARIES),
    )
    if isinstance(error, (*timeouts, TimeoutError)):
        return ModelError(text, code="timeout")

    connection = _loaded(
        *(f"{sdk}.APIConnectionError" for sdk in SDKS),
        *(f"{lib}.TransportError" for lib in HTTP_LIBRARIES),
        "aiohttp.ClientConnectionError",  # DashScope SDK
        "aiohttp.ClientPayloadError",
    )
    if isinstance(error, (*connection, ConnectionError, socket.gaierror, ssl.SSLError)):
        return ModelError(text, code="network")

    status_errors = _loaded(*(f"{sdk}.APIStatusError" for sdk in SDKS))
    if isinstance(error, status_errors):
        codes, _, _ = error_fields(getattr(error, "body", None))
        status = getattr(error, "status_code", None)

        # 流中的错误事件：响应已以 200 开始，状态码不说明错误类别
        code = classify(None if status == 200 else status, codes, known)
        response = getattr(error, "response", None)
        return ModelError(text, code=code, status=status, retry_after=retry_after(getattr(response, "headers", None)))

    api_errors = _loaded(*(f"{sdk}.APIError" for sdk in SDKS))
    if isinstance(error, api_errors):
        # OpenAI 流中的 error 事件：没有状态码，只有错误对象
        codes, _, status = error_fields(getattr(error, "body", None))
        return ModelError(text, code=classify(status, codes, known), status=status)
    return None


def backoff(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    delay = min(cap, base * 2 ** (attempt - 1))
    return delay * random.uniform(0.9, 1.1)
