from __future__ import annotations

import asyncio
import collections
import re
from typing import Any

NAVIGATION_TIMEOUT = 60_000
ACTION_TIMEOUT = 10_000

# Maximum wait for page scripts: if the page hangs (e.g. an infinite loop) the tool reports an error instead of blocking the turn indefinitely
SCRIPT_TIMEOUT = 15

SCROLL_PIXELS = 100
MAX_TEXT = 15_000
LOG_LINES = 200

# Maximum wait for downloads after an action: downloads finishing within this window are reported with this result; the rest are reported in later results
DOWNLOAD_WAIT = 10

SECRET_IN_URL = re.compile(
    r"([?&](?:token|access_token|key|api_key|apikey|auth|password|secret|sig|signature)=)[^&#\s]+",
    re.IGNORECASE,
)


class PageError(Exception): ...


class SensitiveInputError(PermissionError):
    """The policy doesn't allow typing into password, bank card or verification code inputs. kind is focus (current focus) or field (a given element)."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


async def with_timeout(awaitable: Any, seconds: float = SCRIPT_TIMEOUT) -> Any:
    try:
        return await asyncio.wait_for(awaitable, seconds)
    except TimeoutError:
        raise PageError(f"The page hasn't responded in {seconds:g} seconds and may be frozen; reopen the page or use another tab") from None


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
