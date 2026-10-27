from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from work_agent_sdk.core.errors import ConfigError, ToolError
from work_agent_sdk.core.events import MessageUpdated, ModelCalled, StepRecorded
from work_agent_sdk.core.messages import CustomMessage, ToolCall, Usage
from work_agent_sdk.core.requests import Request
from work_agent_sdk.core.service import UNSET
from work_agent_sdk.core.utils import maybe_await

if TYPE_CHECKING:
    from work_agent_sdk.core.tool import Tool
    from work_agent_sdk.models.call import ModelCall
    from work_agent_sdk.runtime.worker.state import CallState
    from work_agent_sdk.runtime.worker.worker import SessionWorker

S = TypeVar("S")


class Suspended(BaseException):  # noqa: N818
    def __init__(self, what: str) -> None:
        super().__init__(what)
        self.what = what


@dataclass
class TurnInfo:
    id: str
    source: str = "user"
    metadata: dict[str, Any] = field(default_factory=dict)
    phase: str = "new"


@dataclass
class CallScope:
    state: CallState
    result_message_id: str
    ordinal: int = 0
    spawns: int = 0
    sends: dict[str, int] = field(default_factory=dict)
    end_turn: bool = False

    def next_ordinal(self) -> int:
        ordinal = self.ordinal
        self.ordinal += 1
        return ordinal


def require_scope(scope: CallScope | None, what: str) -> CallScope:
    if scope is None:
        raise ConfigError(f"{what} can only be used within a tool call (tools, before_tool, after_tool)")
    return scope


def jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return str(value)


class RunContext:
    def __init__(
        self,
        worker: SessionWorker,
        *,
        turn: TurnInfo | None = None,
        tool: Tool | None = None,
        call: ToolCall | None = None,
        scope: CallScope | None = None,
        declared: frozenset[str] = frozenset(),
    ) -> None:
        self._worker = worker
        self._scope = scope
        self._declared = declared
        self.turn = turn
        self.tool = tool
        self.call = call

    def __repr__(self) -> str:
        return f"Context(session={self.session_id!r}, tool={getattr(self.tool, 'name', None)!r})"

    @property
    def session_id(self) -> str:
        return self._worker.session_id

    @property
    def root_id(self) -> str:
        return self._worker.record.root_id

    @property
    def parent_id(self) -> str | None:
        return self._worker.record.parent_id

    @property
    def agent(self) -> str:
        return self._worker.record.agent

    @property
    def turn_id(self) -> str | None:
        return self.turn.id if self.turn else None

    @property
    def model(self) -> Any:
        return self._worker.model

    @property
    def session(self) -> Any:
        return self._worker.sessions.session(self.session_id)

    async def resource(self, name: str, *, wait: bool = True) -> Any:
        return await self._worker.resources.get(name, wait=wait)

    def has_resource(self, name: str) -> bool:
        return bool(self._worker.resources.has(name))

    def _shortcut(self, name: str) -> Any:
        if not self._worker.resources.has(name):
            return None

        bound = self._worker.resources.bound(name)
        if bound is not None and name in self._declared:
            return bound
        raise ConfigError(
            f"ctx.{name} only provides bound resources; declare {name!r} in the tool's requires, or use await ctx.resource({name!r}) instead"
        )

    @property
    def workspace(self) -> Any:
        return self._shortcut("workspace")

    @property
    def computer(self) -> Any:
        return self._shortcut("computer")

    @property
    def browser(self) -> Any:
        return self._shortcut("browser")

    def service(self, kind: type[S]) -> S:
        return self._worker.core.service(kind)

    @property
    def tasks(self) -> Any:
        if self._worker.record.parent_id is not None:
            raise ConfigError("Child sessions can't create further child sessions")
        from work_agent_sdk.runtime.tasks import TaskControlImpl

        return TaskControlImpl(self, self._worker, self._scope)

    def step_key(self, name: str) -> str:
        anchor = self.call.id if self.call is not None else (self.turn_id or "session")
        return f"{self.session_id}:{anchor}:{name}"

    async def step(self, name: str, fn: Callable[[], Any]) -> Any:
        call_state = require_scope(self._scope, "ctx.step").state
        if name in call_state.steps:
            return call_state.steps[name]

        value = jsonable(await maybe_await(fn()))
        await self._worker.append(
            StepRecorded(
                call_id=call_state.id,
                name=name,
                value=value,
                turn_id=self.turn_id,
            )
        )
        return value

    async def wait_for(self, request: Request) -> Any:
        scope = require_scope(self._scope, "ctx.wait_for")
        call_state = scope.state
        ordinal = scope.next_ordinal()
        recorded = next((item for item in call_state.requests if item.ordinal == ordinal), None)
        if recorded is None:
            await self._worker.requests.open(self, request, ordinal)
            raise Suspended("request")
        if recorded.type != request.type_name():
            raise ToolError(
                f"The request waited on during re-execution doesn't match the record (recorded {recorded.type}, now {request.type_name()})",
                code="replay_mismatch",
            )
        if recorded.pending:
            raise Suspended("request")
        if recorded.status != "answered":
            raise ToolError(f"This request's status is {recorded.status} and can't continue", code=recorded.status)
        return await self._worker.requests.resolve(recorded, request)

    async def stream(self, data: Any) -> None:
        if self._scope is None:
            return

        await self._worker.append(
            MessageUpdated(
                message_id=self._scope.result_message_id,
                delta={"progress": jsonable(data)},
                ephemeral=True,
                turn_id=self.turn_id,
            )
        )

    async def add_message(self, message: CustomMessage) -> CustomMessage:
        if message.turn_id is None:
            message.turn_id = self.turn_id
        return await self._worker.add_message(message)

    async def update_message(self, message_id: str, **changes: Any) -> None:
        await self._worker.update_message(
            message_id,
            data=changes.get("data", UNSET),
            display=changes.get("display", UNSET),
            ephemeral=bool(changes.get("ephemeral", False)),
        )

    async def complete_message(self, message_id: str, **changes: Any) -> None:
        await self._worker.complete_message(
            message_id,
            status=changes.get("status", "completed"),
            data=changes.get("data", UNSET),
            for_model=changes.get("for_model", UNSET),
        )

    def end_turn(self) -> None:
        if self._scope is not None:
            self._scope.end_turn = True

    async def generate(
        self,
        prompt: Any,
        *,
        system: str = "",
        thinking: str = "off",
        settings: Any = None,
        output: Any = None,
        model: Any = None,
    ) -> Any:
        from work_agent_sdk.models.call import generate

        chosen = model or self._worker.model
        call_id = self.call.id if self.call else None

        async def record(call: ModelCall, started: float, failure: BaseException | None) -> None:
            builder = call.builder
            segment = self._worker.segment
            if segment is not None and builder.usage is not None:
                segment.usage = segment.usage + builder.usage

            error = getattr(failure, "message", None) or (str(failure) if failure else None)
            await self._worker.append(
                ModelCalled(
                    call_id=call_id or "generate",
                    model=call.model.id,
                    duration=round(time.time() - started, 3),
                    first_token=round(builder.first_token_at - started, 3) if builder.first_token_at else None,
                    usage=builder.usage or Usage(),
                    retries=max(0, call.attempts - 1),
                    error=error[:500] if error else None,
                    error_code=getattr(failure, "code", None),
                    turn_id=self.turn_id,
                )
            )

        return await generate(
            chosen,
            prompt,
            system=system,
            thinking=thinking,
            settings=settings,
            output=output,
            ctx=self,
            on_finished=record,
        )
