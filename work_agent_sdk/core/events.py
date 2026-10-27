from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from work_agent_sdk.core.messages import Message, Usage
from work_agent_sdk.core.requests import PendingRequest
from work_agent_sdk.core.results import TaskResult, TurnResult


class Event(BaseModel):
    type: ClassVar[str] = ""
    stored: ClassVar[bool] = True
    public: ClassVar[bool] = True

    session_id: str | None = None
    seq: int | None = None
    turn_id: str | None = None
    ts: float = Field(default_factory=time.time)

    BASE_FIELDS: ClassVar[set[str]] = {"session_id", "seq", "turn_id", "ts"}

    @property
    def persisted(self) -> bool:
        return self.stored

    def payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude=self.BASE_FIELDS)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, **self.model_dump(mode="json")}


class SessionStarted(Event):
    type: ClassVar[str] = "session_started"
    agent: str
    parent_id: str | None = None
    root_id: str
    forked_from: str | None = None


class SessionEnded(Event):
    type: ClassVar[str] = "session_ended"
    outcome: str


class SessionRewound(Event):
    type: ClassVar[str] = "session_rewound"
    message_id: str
    hidden: list[str] = Field(default_factory=list)


class SessionDeleted(Event):
    type: ClassVar[str] = "session_deleted"
    stored: ClassVar[bool] = False


class TurnStarted(Event):
    type: ClassVar[str] = "turn_started"
    phase: str = "new"  # new / resume / recover
    source: str = "user"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TurnEnded(Event):
    type: ClassVar[str] = "turn_ended"
    result: TurnResult


class MessageStarted(Event):
    type: ClassVar[str] = "message_started"
    message: Message


class MessageUpdated(Event):
    type: ClassVar[str] = "message_updated"
    message_id: str
    changes: dict[str, Any] = Field(default_factory=dict)
    delta: dict[str, Any] | None = None
    message: Message | None = None
    ephemeral: bool = False

    @property
    def persisted(self) -> bool:
        return not self.ephemeral


class MessageCompleted(Event):
    type: ClassVar[str] = "message_completed"
    message: Message


class RequestOpened(Event):
    type: ClassVar[str] = "request_opened"
    request: PendingRequest
    ordinal: int = 0


class RequestClosed(Event):
    type: ClassVar[str] = "request_closed"
    request_id: str
    call_id: str | None = None
    status: str
    answer: Any = None


class TaskAwaited(Event):
    type: ClassVar[str] = "task_awaited"
    public: ClassVar[bool] = False
    call_id: str
    task_id: str
    ordinal: int = 0
    prompt: str = ""  # Task description: tasks not yet queued into child sessions at shutdown are queued after restart


class TaskSettled(Event):
    type: ClassVar[str] = "task_settled"
    public: ClassVar[bool] = False
    task_id: str
    result: TaskResult


class QueueChanged(Event):
    type: ClassVar[str] = "queue_changed"
    stored: ClassVar[bool] = False
    items: list[dict[str, Any]] = Field(default_factory=list)


class ModelCalled(Event):
    type: ClassVar[str] = "model_called"
    public: ClassVar[bool] = False
    call_id: str | None = None
    model: str = ""
    duration: float = 0.0
    first_token: float | None = None
    usage: Usage = Field(default_factory=Usage)
    retries: int = 0
    error: str | None = None
    error_code: str | None = None


class ModelRetried(Event):
    type: ClassVar[str] = "model_retried"
    attempt: int
    delay: float
    error: str
    error_code: str | None = None


class StepRecorded(Event):
    type: ClassVar[str] = "step_recorded"
    public: ClassVar[bool] = False
    call_id: str
    name: str
    value: Any = None


class HookApplied(Event):
    type: ClassVar[str] = "hook_applied"
    hook: str
    point: str
    action: str
    detail: str = ""
    call_id: str | None = None


class NodeConnected(Event):
    type: ClassVar[str] = "node_connected"
    stored: ClassVar[bool] = False
    node: str
    detail: dict[str, Any] = Field(default_factory=dict)


class NodeDisconnected(Event):
    type: ClassVar[str] = "node_disconnected"
    stored: ClassVar[bool] = False
    node: str
    detail: dict[str, Any] = Field(default_factory=dict)


class NodeRefused(Event):
    type: ClassVar[str] = "node_refused"
    stored: ClassVar[bool] = False
    node: str
    detail: dict[str, Any] = Field(default_factory=dict)


ALL_EVENTS: tuple[type[Event], ...] = (
    SessionStarted,
    SessionEnded,
    SessionRewound,
    SessionDeleted,
    TurnStarted,
    TurnEnded,
    MessageStarted,
    MessageUpdated,
    MessageCompleted,
    RequestOpened,
    RequestClosed,
    TaskAwaited,
    TaskSettled,
    QueueChanged,
    ModelCalled,
    ModelRetried,
    StepRecorded,
    HookApplied,
    NodeConnected,
    NodeDisconnected,
    NodeRefused,
)
EVENT_TYPES: dict[str, type[Event]] = {cls.type: cls for cls in ALL_EVENTS}


def parse_event(
    type_name: str, data: dict[str, Any], *, session_id: str | None, seq: int | None, turn_id: str | None, ts: float
) -> Event:
    cls = EVENT_TYPES[type_name]
    return cls.model_validate(
        {
            **data,
            "session_id": session_id,
            "seq": seq,
            "turn_id": turn_id,
            "ts": ts,
        }
    )


class EventBus:
    def __init__(self, limit: int = 10000) -> None:
        self._subscribers: list[tuple[Callable[[Event], bool], asyncio.Queue]] = []
        self._limit = limit

    def publish(self, event: Event) -> None:
        if not event.public:
            return

        for accept, queue in list(self._subscribers):
            if not accept(event):
                continue
            if queue.qsize() >= self._limit:
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(event)

    @contextlib.contextmanager
    def subscription(self, accept: Callable[[Event], bool] = lambda event: True):
        queue: asyncio.Queue = asyncio.Queue()
        entry = (accept, queue)
        self._subscribers.append(entry)

        try:
            yield queue
        finally:
            self._subscribers.remove(entry)

    async def stream(self, accept: Callable[[Event], bool] = lambda event: True) -> AsyncIterator[Event]:
        with self.subscription(accept) as queue:
            while True:
                yield await queue.get()
