from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import work_agent_sdk.core.events as ev
from work_agent_sdk.core.messages import (
    AssistantMessage,
    CustomMessage,
    Message,
    ToolResultMessage,
    parse_message,
)
from work_agent_sdk.core.requests import PendingRequest
from work_agent_sdk.core.results import TaskResult, TurnResult

CONTINUE_KIND = "turn.continue"
OUTPUT_PROBLEM_KIND = "turn.output_problem"


@dataclass
class RequestState:
    id: str
    call_id: str | None
    ordinal: int
    type: str
    data: dict[str, Any]
    answer_schema: dict[str, Any]
    answered_by: str
    turn_id: str | None
    created_at: float
    agent: str
    sensitive: bool = False
    status: str = "pending"  # pending / answered / cancelled / unanswered
    answer: Any = None

    @property
    def pending(self) -> bool:
        return self.status == "pending"

    def to_pending(self, session_id: str) -> PendingRequest:
        return PendingRequest(
            id=self.id,
            type=self.type,
            data=self.data,
            answer_schema=self.answer_schema,
            answered_by=self.answered_by,
            sensitive=self.sensitive,
            session_id=session_id,
            agent=self.agent,
            call_id=self.call_id,
            created_at=self.created_at,
        )


@dataclass
class TaskWait:
    task_id: str
    call_id: str
    ordinal: int
    turn_id: str | None
    prompt: str = ""
    result: TaskResult | None = None

    @property
    def settled(self) -> bool:
        return self.result is not None


@dataclass
class CallState:
    id: str
    name: str
    args: dict[str, Any]
    turn_id: str | None
    index: int
    args_error: str | None = None
    result_id: str | None = None
    steps: dict[str, Any] = field(default_factory=dict)
    requests: list[RequestState] = field(default_factory=list)
    tasks: list[TaskWait] = field(default_factory=list)


@dataclass
class TurnState:
    id: str
    source: str = "user"
    metadata: dict[str, Any] = field(default_factory=dict)
    phase: str = "running"  # running / parked / done
    model_steps: int = 0
    continues: int = 0
    output_retries: int = 0
    result: TurnResult | None = None


class SessionState:
    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.by_id: dict[str, Message] = {}
        self.completion_order: list[str] = []
        self.hidden: set[str] = set()
        self.calls: dict[str, CallState] = {}
        self.requests: dict[str, RequestState] = {}
        self.tasks: dict[str, TaskWait] = {}
        self.turn: TurnState | None = None
        self.turns: dict[str, TurnState] = {}
        self.last_seq = 0
        self.ended: str | None = None
        self.agent = ""

    def message(self, message_id: str) -> Message | None:
        return self.by_id.get(message_id)

    def result_of(self, call: CallState) -> ToolResultMessage | None:
        if call.result_id is None:
            return None
        message = self.by_id.get(call.result_id)
        return message if isinstance(message, ToolResultMessage) else None

    def call_finished(self, call: CallState) -> bool:
        result = self.result_of(call)
        return result is not None and result.finished

    def call_waiting(self, call: CallState) -> bool:
        result = self.result_of(call)
        return result is not None and result.status == "waiting"

    def call_started(self, call: CallState) -> bool:
        return call.result_id is not None

    def resumable(self, call: CallState) -> bool:
        if not self.call_waiting(call):
            return False
        if any(request.status != "answered" for request in call.requests):
            return False
        return all(wait.settled for wait in call.tasks)

    def pending_requests(self) -> list[RequestState]:
        return [request for request in self.requests.values() if request.pending]

    def open_tasks(self, turn_id: str | None = None) -> list[TaskWait]:
        return [
            wait for wait in self.tasks.values() if not wait.settled and (turn_id is None or wait.turn_id == turn_id)
        ]

    def last_assistant(self, turn_id: str) -> AssistantMessage | None:
        for message_id in reversed(self.completion_order):
            message = self.by_id[message_id]
            if isinstance(message, AssistantMessage) and message.turn_id == turn_id and message.status == "completed":
                return message
        return None

    def calls_of(self, message: AssistantMessage) -> list[CallState]:
        return [self.calls[call.id] for call in message.tool_calls if call.id in self.calls]

    def unfinished_calls(self, turn_id: str) -> list[CallState]:
        last = self.last_assistant(turn_id)
        if last is None:
            return []
        return [call for call in self.calls_of(last) if not self.call_finished(call)]

    def waiting_calls(self, turn_id: str | None = None) -> list[CallState]:
        return [
            call
            for call in self.calls.values()
            if self.call_waiting(call) and (turn_id is None or call.turn_id == turn_id)
        ]

    def unfinished_messages(self) -> list[Message]:
        return [message for message in self.messages if message.status in ("in_progress", "waiting")]

    def last_context(self, kind: str) -> CustomMessage | None:
        for message_id in reversed(self.completion_order):
            message = self.by_id[message_id]
            if isinstance(message, CustomMessage) and message.kind == kind:
                return message
        return None

    def apply(self, event: ev.Event) -> None:
        if event.seq is not None:
            self.last_seq = event.seq
        handler = _HANDLERS.get(type(event))
        if handler is not None:
            handler(self, event)

    def put_message(self, message: Message) -> None:
        if message.id not in self.by_id:
            self.messages.append(message)
        else:
            index = next(i for i, item in enumerate(self.messages) if item.id == message.id)
            self.messages[index] = message
        self.by_id[message.id] = message


def _turn(state: SessionState, turn_id: str) -> TurnState:
    turn = state.turns.get(turn_id)
    if turn is None:
        turn = state.turns[turn_id] = TurnState(id=turn_id)
    return turn


def _session_started(state: SessionState, event: ev.SessionStarted) -> None:
    state.agent = event.agent


def _session_ended(state: SessionState, event: ev.SessionEnded) -> None:
    state.ended = event.outcome


def _rewound(state: SessionState, event: ev.SessionRewound) -> None:
    state.hidden.update(event.hidden)


def _turn_started(state: SessionState, event: ev.TurnStarted) -> None:
    turn = _turn(state, event.turn_id or "")
    if event.phase == "new":
        turn.source = event.source
        turn.metadata = dict(event.metadata)

    turn.phase = "running"
    state.turn = turn


def _turn_ended(state: SessionState, event: ev.TurnEnded) -> None:
    turn = _turn(state, event.turn_id or "")
    turn.result = event.result
    if event.result.status == "waiting":
        turn.phase = "parked"
        state.turn = turn
    else:
        turn.phase = "done"
        if state.turn is turn:
            state.turn = None


def _register_calls(state: SessionState, message: AssistantMessage) -> None:
    for index, call in enumerate(message.tool_calls):
        if call.id not in state.calls:
            state.calls[call.id] = CallState(
                id=call.id,
                name=call.name,
                args=dict(call.args),
                turn_id=message.turn_id,
                index=index,
                args_error=call.args_error,
            )


def _message_started(state: SessionState, event: ev.MessageStarted) -> None:
    message = parse_message(event.message)
    state.put_message(message)
    if isinstance(message, ToolResultMessage):
        call = state.calls.get(message.tool_call_id)
        if call is not None:
            call.result_id = message.id


def _message_updated(state: SessionState, event: ev.MessageUpdated) -> None:
    message = state.by_id.get(event.message_id)
    if message is None or not event.changes:
        return

    allowed = {key: value for key, value in event.changes.items() if key in ("data", "display", "status")}
    updated = message.model_copy(update=allowed)
    state.put_message(updated)


def _message_completed(state: SessionState, event: ev.MessageCompleted) -> None:
    message = parse_message(event.message)
    state.put_message(message)

    if message.id not in state.completion_order:
        state.completion_order.append(message.id)

    if isinstance(message, AssistantMessage) and message.status == "completed":
        _register_calls(state, message)
    elif isinstance(message, ToolResultMessage):
        call = state.calls.get(message.tool_call_id)
        if call is not None:
            call.result_id = message.id
    elif isinstance(message, CustomMessage) and message.turn_id and message.turn_id in state.turns:
        if message.kind == CONTINUE_KIND:
            state.turns[message.turn_id].continues += 1
        elif message.kind == OUTPUT_PROBLEM_KIND:
            state.turns[message.turn_id].output_retries += 1


def _request_opened(state: SessionState, event: ev.RequestOpened) -> None:
    pending = event.request
    request = RequestState(
        id=pending.id,
        call_id=pending.call_id,
        ordinal=event.ordinal,
        type=pending.type,
        data=pending.data,
        answer_schema=pending.answer_schema,
        answered_by=pending.answered_by,
        sensitive=pending.sensitive,
        turn_id=event.turn_id,
        created_at=pending.created_at,
        agent=pending.agent,
    )
    state.requests[request.id] = request
    call = state.calls.get(pending.call_id or "")
    if call is not None:
        call.requests.append(request)


def _request_closed(state: SessionState, event: ev.RequestClosed) -> None:
    request = state.requests.get(event.request_id)
    if request is None:
        return

    request.status = event.status
    request.answer = event.answer


def _task_awaited(state: SessionState, event: ev.TaskAwaited) -> None:
    wait = TaskWait(
        task_id=event.task_id, call_id=event.call_id, ordinal=event.ordinal, turn_id=event.turn_id, prompt=event.prompt
    )
    state.tasks[event.task_id] = wait
    call = state.calls.get(event.call_id)
    if call is not None:
        call.tasks.append(wait)


def _task_settled(state: SessionState, event: ev.TaskSettled) -> None:
    wait = state.tasks.get(event.task_id)
    if wait is not None:
        wait.result = event.result


def _step_recorded(state: SessionState, event: ev.StepRecorded) -> None:
    call = state.calls.get(event.call_id)
    if call is not None:
        call.steps[event.name] = event.value


def _model_called(state: SessionState, event: ev.ModelCalled) -> None:
    if event.call_id is None and event.turn_id and event.error is None:
        _turn(state, event.turn_id).model_steps += 1


_HANDLERS: dict[type, Any] = {
    ev.SessionStarted: _session_started,
    ev.SessionEnded: _session_ended,
    ev.SessionRewound: _rewound,
    ev.TurnStarted: _turn_started,
    ev.TurnEnded: _turn_ended,
    ev.MessageStarted: _message_started,
    ev.MessageUpdated: _message_updated,
    ev.MessageCompleted: _message_completed,
    ev.RequestOpened: _request_opened,
    ev.RequestClosed: _request_closed,
    ev.TaskAwaited: _task_awaited,
    ev.TaskSettled: _task_settled,
    ev.StepRecorded: _step_recorded,
    ev.ModelCalled: _model_called,
}


def build_state(events: list[ev.Event]) -> SessionState:
    state = SessionState()
    for event in events:
        state.apply(event)
    return state
