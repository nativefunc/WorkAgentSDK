from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from work_agent_sdk.core.messages import CustomMessage

if TYPE_CHECKING:
    from work_agent_sdk.core.results import TurnResult
    from work_agent_sdk.core.secrets import KeyProvider
    from work_agent_sdk.core.tool import Toolset

S = TypeVar("S")

LIFECYCLE_POINTS = (
    "runner_started",
    "runner_stopping",
    "runner_stopped",
    "session_started",
    "turn_started",
    "turn_ended",
    "call_cancelled",
    "session_stopped",
    "session_closing",
    "session_deleted",
    "toolset_added",
    "toolset_removed",
)


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET: Any = _Unset()


def is_unset(value: Any) -> bool:
    return value is UNSET


@dataclass(frozen=True)
class SessionRef:
    """服务可见的会话信息（只读）。"""

    id: str
    root_id: str
    parent_id: str | None
    agent: str
    resources: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    task_mode: str | None = None
    # 会话所用 Agent 的工具集，供服务读取工具的设置（如 Shell 是否允许在沙箱外执行）
    toolsets: tuple[Toolset, ...] = ()

    @property
    def top_level(self) -> bool:
        return self.parent_id is None


class NodeLookup(Protocol):
    async def get(self, name: str, *, root_id: str, wait: bool = True) -> Any: ...
    def online(self, name: str, *, root_id: str) -> bool | None: ...
    def cached_info(self, name: str, *, root_id: str) -> Any: ...
    def isolated(self, name: str) -> bool: ...
    def known(self, name: str) -> bool: ...
    def shared_folders(self, name: str) -> list[tuple[str, str]]: ...


class RunnerAPI(Protocol):
    """所有服务在 attach 时获得同一个 RunnerAPI，服务只能通过它执行以下操作。"""

    @property
    def secret_key(self) -> KeyProvider | None: ...
    @property
    def nodes(self) -> NodeLookup: ...

    def files(self, name: str) -> Path: ...
    def service(self, kind: type[S]) -> S: ...
    async def session(self, session_id: str) -> SessionRef | None: ...
    async def lineage(self, session_id: str) -> list[str]: ...
    async def descendants(self, session_id: str) -> list[str]: ...
    async def resource(self, session_id: str, name: str) -> Any: ...
    async def model(self, session_id: str) -> Any: ...
    async def add_message(self, session_id: str, message: CustomMessage) -> CustomMessage: ...
    async def update_message(
        self, session_id: str, message_id: str, *, data: Any = UNSET, display: Any = UNSET, ephemeral: bool = False
    ) -> None: ...
    async def complete_message(
        self,
        session_id: str,
        message_id: str,
        *,
        status: str = "completed",
        data: Any = UNSET,
        for_model: Any = UNSET,
    ) -> None: ...
    async def enqueue(
        self, session_id: str, message: CustomMessage, *, source: str, metadata: dict[str, Any] | None = None
    ) -> None: ...
    async def answer(self, session_id: str, request_id: str, value: Any) -> None: ...
    async def pending(self, session_id: str) -> list[Any]: ...
    def run_in_background(self, coroutine: Coroutine[Any, Any, Any]) -> asyncio.Task: ...


class Service:
    """Runner 上每种只有一个实例的组件。provides 为提供的资源名；生命周期方法仅在实现时被调用。"""

    provides: str | None = None
    api: RunnerAPI

    async def attach(self, api: RunnerAPI) -> None:
        self.api = api

    def check(self, config: dict[str, Any]) -> None:
        """创建会话时检查该资源的配置，不合法时抛出 ConfigError。"""

    async def bind(self, session: SessionRef) -> Any:
        """首次使用时绑定资源，返回 ctx.workspace 这类对象。"""
        raise NotImplementedError

    async def unbind(self, session: SessionRef, bound: Any) -> None:
        """与 bind 成对：会话关闭时，对该会话实际绑定过的资源调用一次，bound 为 bind 当时的返回值。"""

    async def ready(self, session: SessionRef) -> bool:
        """返回当前绑定是否需要等待（如等待设备连接）。ctx.resource(name, wait=False) 据此决定是否跳过绑定。"""
        return True

    async def facts(self, session: SessionRef) -> Any:
        """返回提供给模型的资源状况（可比较的数据；None 表示无需说明）。不得触发绑定。"""
        return None

    def render(self, facts: Any) -> str:
        """将资源状况渲染为提供给模型的文字。"""
        return str(facts)

    def config_of(self, value: Any) -> dict[str, Any]:
        """将开发者提供的配置对象转换为保存到会话中的数据（支持 to_config() 或 pydantic 模型）。"""
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "to_config"):
            return value.to_config()
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")

        from work_agent_sdk.core.errors import ConfigError

        raise ConfigError(f"资源 {self.provides} 的配置须为 pydantic 模型或提供 to_config()：{value!r}")

    def implements(self, point: str) -> bool:
        method = getattr(type(self), point, None)
        return method is not None and method is not getattr(Service, point, None)

    async def runner_started(self) -> None: ...
    async def runner_stopping(self) -> None: ...
    async def runner_stopped(self) -> None: ...
    async def session_started(self, session: SessionRef) -> None:
        """与 SessionStarted 事件同时：会话记录写入存储后调用一次（新建、fork、子会话）；重启后载入已有会话不会调用。"""

    async def turn_started(self, session: SessionRef, turn_id: str, phase: str) -> None:
        """与 turn_ended 成对：每一段开始时调用，phase 为 new / resume / recover。"""

    async def turn_ended(self, session: SessionRef, result: TurnResult) -> None: ...
    async def call_cancelled(self, session: SessionRef, call_id: str) -> None: ...
    async def session_stopped(self, session: SessionRef, everything: bool) -> None: ...
    async def session_closing(self, session: SessionRef) -> None: ...
    async def session_deleted(self, session: SessionRef) -> None: ...
    async def toolset_added(self, toolset: Toolset) -> None: ...
    async def toolset_removed(self, toolset: Toolset) -> None: ...
