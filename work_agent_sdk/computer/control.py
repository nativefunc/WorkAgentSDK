from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import work_agent_sdk.strings.computer as strings
from work_agent_sdk.computer.store import ComputerStore
from work_agent_sdk.core.errors import ToolError
from work_agent_sdk.host.screen.policy import Hold

# Maximum seconds sessions wait for each other for the screen; waiting for the user to end a takeover is not subject to this limit
SESSION_WAIT_SECONDS = 30


@dataclass(frozen=True)
class ControlState:
    """Control state of the screen. expires_at is when the user takeover expires (Unix timestamp); None when the takeover never expires or there is no takeover."""

    by_user: bool
    expires_at: float | None
    session_id: str | None


@dataclass
class _Screen:
    root: str | None = None
    holder: str | None = None
    hold: str = Hold.TURN
    user: bool = False
    timeout: float | None = None
    until: float | None = None
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)

    def free_for(self, session_id: str, root_id: str) -> bool:
        return self.root in (None, root_id) and self.holder in (None, session_id)


class ScreenControl:
    def __init__(self, store: Callable[[], ComputerStore]) -> None:
        self._store = store
        self._screens: dict[str, _Screen] = {}
        self._loading = asyncio.Lock()

    async def _screen(self, key: str) -> _Screen:
        screen = self._screens.get(key)
        if screen is not None:
            return screen

        async with self._loading:
            if key not in self._screens:
                screen = _Screen()
                record = await self._store().get_takeover(key)
                if record is not None:
                    screen.user, screen.timeout = True, record["timeout"]
                    screen.until = time.time() + screen.timeout if screen.timeout is not None else None

                self._screens[key] = screen

        return self._screens[key]

    async def _expire(self, key: str, screen: _Screen) -> None:
        if screen.user and screen.until is not None and time.time() >= screen.until:
            await self._end_takeover(key, screen)

    async def _end_takeover(self, key: str, screen: _Screen) -> None:
        screen.user, screen.timeout, screen.until = False, None, None
        await self._store().delete_takeover(key)
        screen.changed.notify_all()

    async def acquire(self, key: str, *, session_id: str, root_id: str, hold: str) -> str | None:
        screen = await self._screen(key)
        loop = asyncio.get_running_loop()
        waited: str | None = None
        deadline: float | None = None
        async with screen.changed:
            while True:
                await self._expire(key, screen)

                if screen.user:
                    remaining = None if screen.until is None else max(0.0, screen.until - time.time())
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(screen.changed.wait(), remaining)
                    continue
                if screen.free_for(session_id, root_id):
                    break

                waited = screen.holder or screen.root

                if deadline is None:
                    deadline = loop.time() + SESSION_WAIT_SECONDS

                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise ToolError(strings.BUSY.format(seconds=SESSION_WAIT_SECONDS), code="busy")

                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(screen.changed.wait(), remaining)

            screen.root, screen.holder, screen.hold = root_id, session_id, hold

        return waited

    async def release_session(self, session_id: str) -> None:
        for screen in list(self._screens.values()):
            if screen.holder != session_id:
                continue
            async with screen.changed:
                screen.holder = None
                if screen.hold == Hold.TURN:
                    screen.root = None
                screen.changed.notify_all()

    async def release_tree(self, root_id: str) -> None:
        for screen in list(self._screens.values()):
            if screen.root != root_id:
                continue
            async with screen.changed:
                screen.root = None
                screen.holder = None
                screen.changed.notify_all()

    async def take(self, key: str, timeout: float | None) -> ControlState:
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be greater than 0; pass None for no expiry")

        screen = await self._screen(key)
        async with screen.changed:
            screen.user, screen.timeout = True, timeout
            screen.until = time.time() + timeout if timeout is not None else None
            await self._store().put_takeover(key, timeout)

        return self._state(screen)

    async def renew(self, key: str) -> bool:
        screen = await self._screen(key)
        async with screen.changed:
            await self._expire(key, screen)

            if not screen.user:
                return False
            if screen.timeout is not None:
                screen.until = time.time() + screen.timeout

            return True

    async def release(self, key: str) -> None:
        screen = await self._screen(key)
        async with screen.changed:
            if screen.user:
                await self._end_takeover(key, screen)

    async def state(self, key: str) -> ControlState:
        screen = await self._screen(key)
        async with screen.changed:
            await self._expire(key, screen)
            return self._state(screen)

    @staticmethod
    def _state(screen: _Screen) -> ControlState:
        return ControlState(
            by_user=screen.user, expires_at=screen.until if screen.user else None, session_id=screen.holder
        )
