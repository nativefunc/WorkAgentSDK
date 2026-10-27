from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from work_agent_sdk.core.errors import ConfigError

if TYPE_CHECKING:
    from work_agent_sdk.runtime.worker.worker import SessionWorker

logger = logging.getLogger("work_agent_sdk")


class Resources:
    def __init__(self, worker: SessionWorker) -> None:
        self.worker = worker
        self._bound: dict[str, Any] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def names(self) -> list[str]:
        return list(self.worker.record.config.resources)

    def has(self, name: str) -> bool:
        return name in self.worker.record.config.resources

    def bound(self, name: str) -> Any:
        return self._bound.get(name)

    async def get(self, name: str, *, wait: bool = True) -> Any:
        if not self.has(name):
            return None
        if name in self._bound:
            return self._bound[name]

        if not wait:
            provider = self.worker.core.provider(name)
            if provider is None or not await provider.ready(await self.worker.session_ref()):
                return None

        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            if name not in self._bound:
                provider = self.worker.core.provider(name)
                if provider is None:
                    raise ConfigError(f"No service provides resource {name!r}; register a Service with provides={name!r}")
                self._bound[name] = await provider.bind(await self.worker.session_ref())

        return self._bound[name]

    async def bind_all(self, names: frozenset[str]) -> None:
        for name in sorted(names):
            if self.has(name):
                await self.get(name)

    async def release(self) -> None:
        bound, self._bound = self._bound, {}
        if not bound:
            return

        session = await self.worker.session_ref()
        for name, value in bound.items():
            provider = self.worker.core.provider(name)
            if provider is None:
                continue
            try:
                await provider.unbind(session, value)
            except Exception:
                logger.exception("Service %s failed to unbind resource %s", type(provider).__name__, name)

    def forget(self) -> None:
        self._bound.clear()
