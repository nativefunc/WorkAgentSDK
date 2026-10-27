from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import work_agent_sdk.strings.computer as strings
from work_agent_sdk.computer.config import Computer
from work_agent_sdk.computer.control import ControlState, ScreenControl
from work_agent_sdk.computer.store import ComputerStore, SqliteComputerStore
from work_agent_sdk.core.errors import ConfigError
from work_agent_sdk.core.results import TurnResult
from work_agent_sdk.core.service import Service, SessionRef
from work_agent_sdk.host.screen.policy import TIERS, ComputerMode, ComputerPolicy, DeviceCeiling, Tier, default_tier
from work_agent_sdk.nodes.files import LazyFiles, NodeHost, ScopedFiles

# Default user takeover timeout in seconds: the takeover ends automatically when there is no action, renewal or live viewing during this time
TAKEOVER_TIMEOUT = 60
logger = logging.getLogger("work_agent_sdk")


@dataclass
class ComputerFrame:

    image: bytes
    width: int
    height: int
    real_width: int
    real_height: int


class _ScreenWatch:
    def __init__(
        self,
        control: ScreenControl,
        capture: Callable[..., Awaitable[Any]],
        key: str,
        max_fps: float,
        max_size: tuple[int, int],
    ) -> None:
        self.control = control
        self.capture = capture
        self.key = key
        self.interval = 1 / max(0.1, max_fps)
        self.max_size = max_size
        self.watchers: set[asyncio.Queue] = set()
        self.task: asyncio.Task | None = None
        self.last: ComputerFrame | None = None

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        if self.last is not None:
            queue.put_nowait(self.last)

        self.watchers.add(queue)

        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._poll(), name=f"work_agent_sdk:watch:{self.key}")

        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> bool:
        self.watchers.discard(queue)

        if self.watchers:
            return False
        if self.task is not None:
            self.task.cancel()

        return True

    async def _poll(self) -> None:
        digest: str | None = None
        loop = asyncio.get_running_loop()
        control = self.control
        while self.watchers:
            started = loop.time()

            # Someone is watching the live view, so the user is still there: renew if a takeover is active
            await control.renew(self.key)

            try:
                result = await self.capture("screenshot", max_size=list(self.max_size), unless_hash=digest)
            except PermissionError:
                # The device owner has paused: the stream pauses too and resumes afterwards
                result = None
            except Exception as error:
                logger.debug("Live view screenshot failed: %s", error)
                result = None

            if result and not result.get("unchanged"):
                digest = result.get("hash")
                self.last = ComputerFrame(
                    image=base64.b64decode(result["image"]),
                    width=int(result["width"]),
                    height=int(result["height"]),
                    real_width=int(result["real_width"]),
                    real_height=int(result["real_height"]),
                )
                for queue in list(self.watchers):
                    if queue.full():
                        queue.get_nowait()  # Slow viewer: drop old frames and keep only the latest
                    queue.put_nowait(self.last)

            await asyncio.sleep(max(0.0, self.interval - (loop.time() - started)))


class BoundComputer:
    """
    The computer bound to a session, i.e. the object returned by ctx.computer and await session.computer(). Connects to the node on the first action.
    """

    def __init__(self, config: Computer, session: SessionRef, service: ComputerService) -> None:
        self.config = config
        self.session = session
        self._service = service
        self.real_size: tuple[int, int] | None = None

    def __repr__(self) -> str:
        return f"Computer({self.config.node!r})"

    @property
    def policy(self) -> ComputerPolicy:
        return self.config.policy

    @property
    def description(self) -> str:
        return self.config.description

    async def screen_key(self) -> str:
        """Screen identifier used to separate control and live views. Omitting display and explicitly specifying the default display give the same value."""
        node = await self.node()
        return f"computer:{node.name}:{node.screen_display(self.config.display) or ''}"

    async def node(self) -> Any:
        return await self._service.api.nodes.get(self.config.node, root_id=self.session.root_id)

    async def claim(self) -> str | None:
        return await self._service.control.acquire(
            await self.screen_key(), session_id=self.session.id, root_id=self.session.root_id, hold=self.policy.hold
        )

    async def take_control(self, *, timeout: float | None = TAKEOVER_TIMEOUT) -> ControlState:
        """The user takes over this screen. After the action in progress finishes, the agent's actions (including other sessions') wait. Never expires when timeout is None."""
        return await self._service.control.take(await self.screen_key(), timeout)

    async def keep_control(self) -> bool:
        """Renew the takeover; returns whether it is still active."""
        return await self._service.control.renew(await self.screen_key())

    async def release_control(self) -> None:
        await self._service.control.release(await self.screen_key())

    async def control(self) -> ControlState:
        return await self._service.control.state(await self.screen_key())

    async def grants(self) -> dict[str, Any]:
        """Return the current grants {"apps": {app: tier}, "system_keys": bool}."""
        record = await self._service.store.get_grants(self.session.root_id)
        return record or {"apps": {}, "system_keys": False}

    async def grant(
        self, apps: dict[str, str], *, system_keys: bool = False, names: dict[str, str] | None = None
    ) -> None:
        current = await self.grants()
        current["apps"] = {**current.get("apps", {}), **apps}
        current["names"] = {**(current.get("names") or {}), **(names or {})}
        current["system_keys"] = bool(current.get("system_keys")) or system_keys
        await self._service.store.put_grants(self.session.root_id, current)

    async def _rules(self) -> dict[str, Any]:
        # Grant rules sent to the executor; app names are only used to list authorized apps to the model
        grants = await self.grants()
        return {"apps": grants.get("apps") or {}, "system_keys": bool(grants.get("system_keys"))}

    async def ceiling(self) -> DeviceCeiling | None:
        """The cap the device owner set for the screen; None when there is no cap or it hasn't connected yet."""
        info = self._service.api.nodes.cached_info(self.config.node, root_id=self.session.root_id)
        return info.screen_ceiling if info is not None else None

    async def _call(self, op: str, **arguments: Any) -> Any:
        node = await self.node()
        return await node.computer(op, node.screen_display(self.config.display), **arguments)

    async def screenshot(
        self, *, max_size: tuple[int, int] | None = None, region: tuple[int, int, int, int] | None = None
    ) -> tuple[bytes, tuple[int, int]]:
        """Take a screenshot; returns (JPEG data, image size). region is in real screen pixels."""
        result = await self._call(
            "screenshot", max_size=list(max_size) if max_size else None, region=list(region) if region else None
        )
        self.real_size = (int(result["real_width"]), int(result["real_height"]))
        return base64.b64decode(result["image"]), (int(result["width"]), int(result["height"]))

    async def size(self) -> tuple[int, int]:
        if self.real_size is None:
            width, height = await self._call("size")
            self.real_size = (int(width), int(height))
        return self.real_size

    async def act(self, action: str, args: dict[str, Any]) -> Any:
        """Perform an action with coordinates in real screen pixels; raises PermissionError when a rule is violated."""
        return await self._call(
            "act",
            action=action,
            args=args,
            policy=self.policy.model_dump(mode="json"),
            grants=await self._rules(),
            session=self.session.id,
        )

    async def user_input(self, action: str, args: dict[str, Any]) -> Any:
        """Perform a user action with coordinates in real screen pixels, taking over first if not already. Not bound by app tiers or grants; the device owner's cap and pause still apply."""
        key = await self.screen_key()
        if not await self._service.control.renew(key):
            await self._service.control.take(key, TAKEOVER_TIMEOUT)

        result = await self._call("user_act", action=action, args=args)
        self._service.user_acted.add(key)
        return result

    async def take_user_acted(self) -> bool:
        """Return whether the user has operated this screen since the last check, and clear the flag. Tools use this to warn the model that the screen may have changed."""
        key = await self.screen_key()
        acted = key in self._service.user_acted
        self._service.user_acted.discard(key)
        return acted

    async def watch(
        self, *, max_fps: float = 2, max_size: tuple[int, int] = (1280, 800)
    ) -> AsyncIterator[ComputerFrame]:
        """Live frames. Viewers of the same screen share one stream; stop iterating to stop watching. While the user has taken over and someone is watching, the takeover renews automatically."""
        key = await self.screen_key()
        watch = self._service.watches.get(key)
        if watch is None:
            watch = self._service.watches[key] = _ScreenWatch(self._service.control, self._call, key, max_fps, max_size)

        queue = watch.subscribe()
        try:
            while True:
                yield await queue.get()
        finally:
            if watch.unsubscribe(queue) and self._service.watches.get(key) is watch:
                self._service.watches.pop(key, None)

    async def frontmost(self) -> dict[str, Any] | None:
        return await self._call("frontmost")

    async def apps(self, *, installed: bool = False) -> list[dict[str, Any]]:
        """Return running apps; with installed=True, installed apps are appended after them. Each item is {id, name, exe, pid}."""
        return await self._call("apps", installed=installed) or []

    async def open_app(self, app: str) -> dict[str, Any]:
        """Open an app or bring it to the front (looked up by name or identity), under the same rules as actions. Returns the app; raises RuntimeError if it couldn't be brought to the front."""
        return await self._call(
            "open_app",
            app=app,
            policy=self.policy.model_dump(mode="json"),
            grants=await self._rules(),
            session=self.session.id,
        )

    @property
    def files(self) -> LazyFiles:
        """Files on the node the computer is on. On a device, only directories the device owner exposed can be read or written."""

        async def open_files() -> ScopedFiles:
            node = await self.node()
            info = await node.info()
            files = NodeHost(node, info.style, info.node_paths.transfers)
            return ScopedFiles(files, style=info.style, home=info.home, keep=[info.home])

        return LazyFiles(open_files)


class ComputerService(Service):
    """store holds app grants and user takeovers; uses data_dir/ext/computer/computer.db when omitted."""

    provides = "computer"

    def __init__(self, *, store: ComputerStore | None = None) -> None:
        self._store = store
        self.control = ScreenControl(lambda: self.store)
        self.watches: dict[str, _ScreenWatch] = {}

        # Screens the user has operated that the model hasn't been told about yet
        self.user_acted: set[str] = set()

    @property
    def store(self) -> ComputerStore:
        if self._store is None:
            self._store = SqliteComputerStore(self.api.files("computer") / "computer.db")
        return self._store

    def check(self, config: dict[str, Any]) -> None:
        computer = Computer.model_validate(config)
        if not self.api.nodes.known(computer.node):
            raise ConfigError(f"Node {computer.node!r} referenced by the computer is not registered; register it with Runner(nodes=[...])")

    async def bind(self, session: SessionRef) -> BoundComputer:
        return BoundComputer(Computer.model_validate(session.resources["computer"]), session, self)

    async def facts(self, session: SessionRef) -> Any:
        """Return the computer information described to the model; None when the session has no computer tools."""
        if "computer" not in session.tool_resources:
            return None

        computer = Computer.model_validate(session.resources["computer"])
        info = self.api.nodes.cached_info(computer.node, root_id=session.root_id)
        ceiling = info.screen_ceiling if info is not None else None
        facts: dict[str, Any] = {
            "node": computer.node,
            "shared_folders": self.api.nodes.shared_folders(computer.node),
        }
        if computer.policy.mode == ComputerMode.STANDARD:
            grants = await self.store.get_grants(session.root_id) or {}
            facts["apps"] = authorized_apps(computer.policy, grants, ceiling)
        if ceiling is not None and ceiling.max_tier != Tier.FULL:
            facts["max_tier"] = str(ceiling.max_tier)
        if computer.description:
            facts["description"] = computer.description

        return facts

    def render(self, facts: Any) -> str:
        items = [(strings.FACTS_NODE, facts["node"])]
        if "apps" in facts:
            items.append((strings.FACTS_AUTHORIZED, apps_text(facts["apps"])))
        if facts.get("max_tier") in strings.TIERS:
            items.append((strings.FACTS_LIMIT, strings.FACTS_LIMIT_VALUE.format(tier=strings.TIERS[facts["max_tier"]])))
        for name, path in facts.get("shared_folders") or []:
            items.append((strings.FACTS_SHARED_FOLDER, strings.FACTS_SHARED_FOLDER_VALUE.format(name=name, path=path)))
        if facts.get("description"):
            items.append((strings.FACTS_DESCRIPTION, facts["description"]))

        lines = [strings.FACTS_ITEM.format(name=name, value=value) for name, value in items]
        return "\n".join([strings.FACTS_TITLE, *lines])

    async def turn_ended(self, session: SessionRef, result: TurnResult) -> None:
        await self.control.release_session(session.id)

    async def session_closing(self, session: SessionRef) -> None:
        await self.control.release_session(session.id)
        if session.parent_id is None:
            await self.control.release_tree(session.id)

    async def session_deleted(self, session: SessionRef) -> None:
        if session.parent_id is None and "computer" in session.resources:
            await self.store.delete_grants(session.id)

    async def runner_stopping(self) -> None:
        # Live view polling tasks: stop them before closing the store, otherwise polling reopens the database after it's closed
        tasks = [watch.task for watch in self.watches.values() if watch.task is not None and not watch.task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.watches.clear()

    async def runner_stopped(self) -> None:
        if self._store is not None:
            await self._store.close()


def authorized_apps(
    policy: ComputerPolicy, grants: dict[str, Any], ceiling: DeviceCeiling | None = None
) -> list[list[str | None]]:
    """
    Authorized apps and their effective tiers [[name, tier or None], ...]: developer-allowed apps first, then user-granted ones, deduplicated by name.
    Tiers are capped by the device; when an allow rule contains wildcards and specifies no tier, the tier depends on the specific app and is recorded as None.
    """
    found: dict[str, str | None] = {}
    for pattern, tier in policy.allow.items():
        if not tier and not any(char in pattern for char in "*?["):
            tier = default_tier(policy, {"id": pattern, "name": pattern})
        found.setdefault(str(pattern), str(tier) if tier else None)

    names = grants.get("names") or {}
    for key, tier in (grants.get("apps") or {}).items():
        found.setdefault(str(names.get(key) or key), str(tier))

    capped = []
    for name, tier in found.items():
        if ceiling is not None and tier is not None:
            tier = str(min(Tier(tier), ceiling.max_tier, key=TIERS.index))
        capped.append([name, tier])
    return capped


def apps_text(apps: list[list[str | None]]) -> str:
    """Description of authorized apps: fully operable apps list only the name; restricted ones note their tier."""
    if not apps:
        return strings.NONE
    return strings.FACTS_SEPARATOR.join(
        strings.APP_WITH_TIER.format(app=name, tier=strings.TIERS[tier]) if tier in strings.TIERS else str(name)
        for name, tier in apps
    )
