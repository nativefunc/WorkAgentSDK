from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from work_agent_sdk.core.service import LIFECYCLE_POINTS, Service

logger = logging.getLogger("work_agent_sdk")


class Lifecycle:
    def __init__(self, services: Callable[[], list[Service]]) -> None:
        self._services = services
        self._listeners: dict[str, list[Callable[..., Awaitable[None]]]] = {point: [] for point in LIFECYCLE_POINTS}

    def listen(self, point: str, callback: Callable[..., Awaitable[None]]) -> None:
        if point not in self._listeners:
            raise ValueError(f"未知的生命周期阶段：{point}")
        self._listeners[point].append(callback)

    async def notify(self, point: str, *args: Any) -> None:
        strict = point == "runner_started"
        for service in self._services():
            if not service.implements(point):
                continue
            try:
                await getattr(service, point)(*args)
            except Exception:
                if strict:
                    raise
                logger.exception("服务 %s 在 %s 阶段出错", type(service).__name__, point)

        for callback in list(self._listeners[point]):
            try:
                await callback(*args)
            except Exception:
                if strict:
                    raise
                logger.exception("%s 在 %s 阶段出错", callback, point)
