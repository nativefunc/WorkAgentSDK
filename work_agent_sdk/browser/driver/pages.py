from __future__ import annotations

import asyncio
import collections
import re
from typing import Any

NAVIGATION_TIMEOUT = 60_000
ACTION_TIMEOUT = 10_000

# 页面脚本的最长等待时间：页面卡死（如死循环）时工具报错，避免本轮被一直阻塞
SCRIPT_TIMEOUT = 15

SCROLL_PIXELS = 100
MAX_TEXT = 15_000
LOG_LINES = 200

# 动作结束后等待下载的最长时间：在此期间完成的下载随本次结果告知模型，其余的在后续结果中报告
DOWNLOAD_WAIT = 10

SECRET_IN_URL = re.compile(
    r"([?&](?:token|access_token|key|api_key|apikey|auth|password|secret|sig|signature)=)[^&#\s]+",
    re.IGNORECASE,
)


class PageError(Exception): ...


async def with_timeout(awaitable: Any, seconds: float = SCRIPT_TIMEOUT) -> Any:
    try:
        return await asyncio.wait_for(awaitable, seconds)
    except TimeoutError:
        raise PageError(f"页面 {seconds:g} 秒内无响应，可能已卡死；请重新打开页面或改用其他标签页") from None


def redact_url_secrets(text: str) -> str:
    return SECRET_IN_URL.sub(r"\1***", text)


class Tab:
    def __init__(self, tab_id: str, page: Any, owner: str) -> None:
        self.id = tab_id
        self.page = page

        self.owner = owner
        self.refs: list[Any] = []
        self.console: collections.deque[str] = collections.deque(maxlen=LOG_LINES)
        self.network: collections.deque[str] = collections.deque(maxlen=LOG_LINES)
