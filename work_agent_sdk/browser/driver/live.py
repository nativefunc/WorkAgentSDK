from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from work_agent_sdk.browser.driver.contexts import BrowserContext
    from work_agent_sdk.browser.driver.pages import Tab

logger = logging.getLogger("work_agent_sdk")

# 跟随当前标签页时，检查标签页是否切换的间隔
FOLLOW_CHECK = 0.3


@dataclass
class BrowserFrame:
    """一帧画面（JPEG）。user_input 的坐标以 viewport_width、viewport_height（CSS 像素）为准。"""

    image: bytes
    width: int
    height: int
    viewport_width: int
    viewport_height: int
    tab_id: str
    url: str
    title: str


def jpeg_size(data: bytes) -> tuple[int, int]:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue

        marker = data[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue

        length = int.from_bytes(data[index + 2 : index + 4], "big")

        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            height = int.from_bytes(data[index + 5 : index + 7], "big")
            width = int.from_bytes(data[index + 7 : index + 9], "big")
            return width, height

        index += 2 + length

    return 0, 0


class Screencast:
    def __init__(self, tab: Tab, *, max_size: tuple[int, int], quality: int, max_fps: float) -> None:
        self.tab = tab
        self.max_size = max_size
        self.quality = quality
        self.interval = 1 / max(0.1, max_fps)
        self.watchers: set[asyncio.Queue] = set()
        self.last: BrowserFrame | None = None
        self._cdp: Any = None
        self._last_ack = 0.0
        self._title = ""
        self._title_url = ""

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        if self.last is not None:
            queue.put_nowait(self.last)

        self.watchers.add(queue)

        if self._cdp is None:
            await self._start()

        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.watchers.discard(queue)
        if not self.watchers:
            await self.stop()

    async def _start(self) -> None:
        page = self.tab.page
        cdp = await page.context.new_cdp_session(page)
        cdp.on("Page.screencastFrame", lambda params: asyncio.ensure_future(self._on_frame(params)))
        await cdp.send(
            "Page.startScreencast",
            {"format": "jpeg", "quality": self.quality, "maxWidth": self.max_size[0], "maxHeight": self.max_size[1]},
        )
        self._cdp = cdp

    async def stop(self) -> None:
        cdp, self._cdp = self._cdp, None
        if cdp is None:
            return

        with contextlib.suppress(Exception):
            await cdp.send("Page.stopScreencast")
        with contextlib.suppress(Exception):
            await cdp.detach()

    async def _on_frame(self, params: dict[str, Any]) -> None:
        cdp = self._cdp
        if cdp is None:
            return

        try:
            image = base64.b64decode(params["data"])
            width, height = jpeg_size(image)
            metadata = params.get("metadata") or {}
            page = self.tab.page
            url = page.url
            if url != self._title_url:
                self._title_url = url
                with contextlib.suppress(Exception):
                    self._title = (await asyncio.wait_for(page.title(), 2))[:300]

            self.last = BrowserFrame(
                image=image,
                width=width,
                height=height,
                viewport_width=round(metadata.get("deviceWidth") or 0),
                viewport_height=round(metadata.get("deviceHeight") or 0),
                tab_id=self.tab.id,
                url=url,
                title=self._title,
            )
            for queue in list(self.watchers):
                if queue.full():
                    queue.get_nowait()  # 观看者处理较慢：丢弃旧帧，只保留最新一帧
                queue.put_nowait(self.last)
        except Exception as error:
            logger.debug("画面帧处理失败：%s", error)

        # 推迟确认：浏览器收到确认后才发送下一帧，从源头限制帧率
        loop = asyncio.get_running_loop()
        delay = self._last_ack + self.interval - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)

        self._last_ack = loop.time()

        with contextlib.suppress(Exception):
            await cdp.send("Page.screencastFrameAck", {"sessionId": params.get("sessionId")})


async def follow(
    context: BrowserContext, owner: str, *, max_size: tuple[int, int], quality: int, max_fps: float
) -> AsyncIterator[BrowserFrame]:
    current: Tab | None = None
    cast: Screencast | None = None
    queue: asyncio.Queue | None = None
    try:
        while True:
            tab = context.active.get(owner)
            if tab is not None and tab.page.is_closed():
                tab = None

            if tab is not current:
                if cast is not None and queue is not None:
                    await cast.unsubscribe(queue)

                current, cast, queue = tab, None, None
                if tab is not None:
                    cast = context.screencasts.get(tab.id)
                    if cast is None:
                        cast = Screencast(tab, max_size=max_size, quality=quality, max_fps=max_fps)
                        context.screencasts[tab.id] = cast
                    queue = await cast.subscribe()

            if queue is None:
                await asyncio.sleep(FOLLOW_CHECK)
                continue

            try:
                frame = await asyncio.wait_for(queue.get(), FOLLOW_CHECK)
            except TimeoutError:
                continue

            yield frame
    finally:
        if cast is not None and queue is not None:
            with contextlib.suppress(Exception):
                await cast.unsubscribe(queue)
