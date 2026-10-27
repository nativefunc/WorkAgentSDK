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
    """Session information visible to services (read-only)."""

    id: str
    root_id: str
    parent_id: str | None
    agent: str
    resources: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    task_mode: str | None = None
    # Toolsets actually available to the session (for dynamic subagents, only the selected ones), so services can read tool settings (e.g. whether Shell may run outside the sandbox)
    toolsets: tuple[Toolset, ...] = ()
    # Resources required by the tools actually available to the session; services use this to decide whether to describe the resource to the model
    tool_resources: frozenset[str] = frozenset()

    @property
    def top_level(self) -> bool:
        return self.parent_id is None


class NodeLookup(Protocol):
    async def get(self, name: str, *, root_id: str, wait: bool = True) -> Any: ...
    def online(self, name: str, *, root_id: str) -> bool | None: ...
    def cached_info(self, name: str, *, root_id: str) -> Any: ...
    def known(self, name: str) -> bool: ...
    def shared_folders(self, name: str) -> list[tuple[str, str]]: ...


class RunnerAPI(Protocol):
    """The Runner interface used by services, available as self.api after attach()."""

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
    async def update_resource(self, session_id: str, name: str, config: dict[str, Any]) -> None: ...
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
    """A service that provides resources to sessions; each kind of service has only one instance in the Runner. provides is the name of the resource provided; implement lifecycle methods as needed."""

    provides: str | None = None
    api: RunnerAPI

    async def attach(self, api: RunnerAPI) -> None:
        self.api = api

    def check(self, config: dict[str, Any]) -> None:
        """Validate this resource's configuration when a session is created; raise ConfigError if invalid."""

    async def bind(self, session: SessionRef) -> Any:
        """Called the first time a session uses the resource; returns the resource, e.g. the object returned by ctx.workspace."""
        raise NotImplementedError

    async def unbind(self, session: SessionRef, bound: Any) -> None:
        """Called when a session closes, once, only for sessions that called bind(). bound is the return value of bind()."""

    async def ready(self, session: SessionRef) -> bool:
        """Return whether the resource can be used right away (e.g. the device is connected). When it returns False, ctx.resource(name, wait=False) returns None."""
        return True

    async def facts(self, session: SessionRef) -> Any:
        """Return the resource state described to the model; not sent when identical to the previous turn; nothing is described when it returns None. Must not trigger binding, i.e. must not call self.api.resource()."""
        return None

    def render(self, facts: Any) -> str:
        """Turn the return value of facts() into text sent to the model."""
        return str(facts)

    def config_of(self, value: Any) -> dict[str, Any]:
        """Turn the configuration in resources into a dict stored in the session. Supports pydantic models and objects providing to_config() by default."""
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "to_config"):
            return value.to_config()
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")

        from work_agent_sdk.core.errors import ConfigError

        raise ConfigError(f"The configuration of resource {self.provides} must be a pydantic model or provide to_config(): {value!r}")

    def implements(self, point: str) -> bool:
        method = getattr(type(self), point, None)
        return method is not None and method is not getattr(Service, point, None)

    async def runner_started(self) -> None: ...
    async def runner_stopping(self) -> None: ...
    async def runner_stopped(self) -> None: ...
    async def session_started(self, session: SessionRef) -> None:
        """Called after a session is created, including fork() and child sessions. Not called when existing sessions are loaded after the Runner restarts."""

    async def turn_started(self, session: SessionRef, turn_id: str, phase: str) -> None:
        """Called when a turn starts or continues, paired with turn_ended. phase is new (a new turn), resume (continuing after a pause, e.g. after answering a request) or recover (continuing after the backend restarts)."""

    async def turn_ended(self, session: SessionRef, result: TurnResult) -> None: ...
    async def call_cancelled(self, session: SessionRef, call_id: str) -> None: ...
    async def session_stopped(self, session: SessionRef, everything: bool) -> None: ...
    async def session_closing(self, session: SessionRef) -> None: ...
    async def session_deleted(self, session: SessionRef) -> None: ...
    async def toolset_added(self, toolset: Toolset) -> None: ...
    async def toolset_removed(self, toolset: Toolset) -> None: ...
