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
from work_agent_sdk.host.screen.policy import ComputerPolicy
from work_agent_sdk.nodes.files import LazyFiles, NodeHost, ScopedFiles

# 用户接管的默认超时秒数：期间没有操作、续期或观看实时画面时自动退出接管
TAKEOVER_TIMEOUT = 60
logger = logging.getLogger("work_agent_sdk")


@dataclass
class ComputerFrame:
    """实时画面的一帧（JPEG）。user_input 的坐标以 real_width、real_height（屏幕真实分辨率）为准。"""

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

            # 有人在看实时画面，说明用户仍在：接管中时续期
            await control.renew(self.key)

            try:
                result = await self.capture("screenshot", max_size=list(self.max_size), unless_hash=digest)
            except PermissionError:
                # 设备所有者已暂停：画面同时暂停，恢复后继续推送
                result = None
            except Exception as error:
                logger.debug("实时画面截图失败：%s", error)
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
                        queue.get_nowait()  # 观看者处理较慢：丢弃旧帧，只保留最新一帧
                    queue.put_nowait(self.last)

            await asyncio.sleep(max(0.0, self.interval - (loop.time() - started)))


class BoundComputer:
    """
    绑定到某个会话的电脑，即 ctx.computer 与 await session.computer() 返回的对象。绑定时不连接节点，
    首次执行动作时才连接。
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
        """屏幕标识，控制权和实时画面据此区分。省略 display 与显式指定默认桌面得到同一个值。"""
        node = await self.node()
        return f"computer:{node.name}:{node.screen_display(self.config.display) or ''}"

    async def node(self) -> Any:
        return await self._service.api.nodes.get(self.config.node, root_id=self.session.root_id)

    async def claim(self) -> str | None:
        return await self._service.control.acquire(
            await self.screen_key(), session_id=self.session.id, root_id=self.session.root_id, hold=self.policy.hold
        )

    async def take_control(self, *, timeout: float | None = TAKEOVER_TIMEOUT) -> ControlState:
        """用户接管这块屏幕。正在执行的动作执行完后，智能体（包括其他会话）的动作等待。timeout 为 None 时不过期。"""
        return await self._service.control.take(await self.screen_key(), timeout)

    async def keep_control(self) -> bool:
        """接管续期，返回是否仍在接管中。"""
        return await self._service.control.renew(await self.screen_key())

    async def release_control(self) -> None:
        await self._service.control.release(await self.screen_key())

    async def control(self) -> ControlState:
        return await self._service.control.state(await self.screen_key())

    async def grants(self) -> dict[str, Any]:
        """返回授权信息 {"apps": {应用: 级别}, "system_keys": bool}，随每个动作发送给执行端。"""
        record = await self._service.store.get_grants(self.session.root_id)
        return record or {"apps": {}, "system_keys": False}

    async def grant(self, apps: dict[str, str], *, system_keys: bool = False) -> None:
        current = await self.grants()
        current["apps"] = {**current.get("apps", {}), **apps}
        current["system_keys"] = bool(current.get("system_keys")) or system_keys
        await self._service.store.put_grants(self.session.root_id, current)

    async def _call(self, op: str, **arguments: Any) -> Any:
        node = await self.node()
        return await node.computer(op, node.screen_display(self.config.display), **arguments)

    async def screenshot(
        self, *, max_size: tuple[int, int] | None = None, region: tuple[int, int, int, int] | None = None
    ) -> tuple[bytes, tuple[int, int]]:
        """截图，在执行端完成裁剪和缩放后回传，返回（JPEG 数据，图片尺寸）。region 以真实屏幕像素表示。"""
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
        """执行一个动作，坐标以真实屏幕像素表示；违反规则时抛出 PermissionError。"""
        return await self._call(
            "act",
            action=action,
            args=args,
            policy=self.policy.model_dump(mode="json"),
            grants=await self.grants(),
            session=self.session.id,
        )

    async def user_input(self, action: str, args: dict[str, Any]) -> Any:
        """执行用户的操作，坐标为真实屏幕像素，未接管时先接管。不受应用分级和授权约束，设备所有者的上限和暂停仍然生效。"""
        key = await self.screen_key()
        if not await self._service.control.renew(key):
            await self._service.control.take(key, TAKEOVER_TIMEOUT)

        result = await self._call("user_act", action=action, args=args)
        self._service.user_acted.add(key)
        return result

    async def take_user_acted(self) -> bool:
        """返回自上次查询以来用户是否操作过该屏幕，并清除该标记。工具据此提醒模型画面可能已变化。"""
        key = await self.screen_key()
        acted = key in self._service.user_acted
        self._service.user_acted.discard(key)
        return acted

    async def watch(
        self, *, max_fps: float = 2, max_size: tuple[int, int] = (1280, 800)
    ) -> AsyncIterator[ComputerFrame]:
        """实时画面：执行端按帧率截图，画面未变化时不传输；同一屏幕的观看者共用一路画面。有人观看时，用户接管持续续期。"""
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
        """返回正在运行的应用；installed=True 时其后再附上已安装的应用。每项为 {id, name, exe, pid}。"""
        return await self._call("apps", installed=installed) or []

    async def open_app(self, app: str) -> dict[str, Any]:
        """打开应用或将其切到前台（按名称或身份查找），规则与动作相同。返回该应用；未能切到前台时抛出 RuntimeError。"""
        return await self._call(
            "open_app",
            app=app,
            policy=self.policy.model_dump(mode="json"),
            grants=await self.grants(),
            session=self.session.id,
        )

    @property
    def files(self) -> LazyFiles:
        """电脑所在节点上的文件。在设备上只能读写设备所有者开放的目录。"""

        async def open_files() -> ScopedFiles:
            node = await self.node()
            info = await node.info()
            files = NodeHost(node, info.style, info.node_paths.transfers)
            return ScopedFiles(files, style=info.style, home=info.home, keep=[info.home])

        return LazyFiles(open_files)


class ComputerService(Service):
    """store 为应用授权与用户接管的存储，省略时使用 data_dir/ext/computer/computer.db。"""

    provides = "computer"

    def __init__(self, *, store: ComputerStore | None = None) -> None:
        self._store = store
        self.control = ScreenControl(lambda: self.store)
        self.watches: dict[str, _ScreenWatch] = {}

        # 用户操作过、尚未告知模型的屏幕
        self.user_acted: set[str] = set()

    @property
    def store(self) -> ComputerStore:
        if self._store is None:
            self._store = SqliteComputerStore(self.api.files("computer") / "computer.db")
        return self._store

    def check(self, config: dict[str, Any]) -> None:
        computer = Computer.model_validate(config)
        if not self.api.nodes.known(computer.node):
            raise ConfigError(f"电脑引用的节点 {computer.node!r} 未登记；请通过 Runner(nodes=[...]) 登记该节点")

    async def bind(self, session: SessionRef) -> BoundComputer:
        return BoundComputer(Computer.model_validate(session.resources["computer"]), session, self)

    async def facts(self, session: SessionRef) -> Any:
        computer = Computer.model_validate(session.resources["computer"])
        facts = {
            "node": computer.node,
            "online": self.api.nodes.online(computer.node, root_id=session.root_id),
            "mode": str(computer.policy.mode),
            "shared_folders": self.api.nodes.shared_folders(computer.node),
        }
        if computer.description:
            facts["description"] = computer.description

        return facts

    def render(self, facts: Any) -> str:
        lines = [strings.FACTS_SCREEN.format(node=facts["node"])]
        if facts.get("mode") == "standard":
            lines.append(strings.FACTS_RESTRICTED)
        if facts.get("online") is False:
            lines.append(strings.FACTS_OFFLINE)

        for name, path in facts.get("shared_folders") or []:
            lines.append(strings.FACTS_SHARED_FOLDER.format(name=name, path=path))

        if facts.get("description"):
            lines.append(strings.FACTS_DESCRIPTION.format(description=facts["description"]))

        return "\n".join(lines)

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
        # 实时画面的轮询任务：停掉后再关闭存储，否则轮询会在存储关闭后重新打开数据库
        tasks = [watch.task for watch in self.watches.values() if watch.task is not None and not watch.task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.watches.clear()

    async def runner_stopped(self) -> None:
        if self._store is not None:
            await self._store.close()
