from __future__ import annotations

from collections.abc import Callable

import work_agent_sdk.strings.runtime as strings
from work_agent_sdk.core.messages import (
    AssistantMessage,
    CustomMessage,
    Message,
    TextPart,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from work_agent_sdk.core.untrusted import wrap_context
from work_agent_sdk.runtime.worker.state import CallState, SessionState


def model_view(state: SessionState) -> list[Message]:
    converted: list[Message] = []
    for message_id in state.completion_order:
        if message_id in state.hidden:
            continue

        message = state.by_id[message_id]
        item = _convert(message, state)
        if item is not None:
            converted.append(item)

    return normalize(converted, lambda call: _reason(state, call))


def _convert(message: Message, state: SessionState) -> Message | None:
    if isinstance(message, UserMessage):
        return message
    if isinstance(message, AssistantMessage):
        if message.status == "completed":
            return message

        text = [part for part in message.content if isinstance(part, TextPart) and part.text]
        if not text:
            return None
        return message.model_copy(update={"content": text, "tool_calls": []})
    if isinstance(message, ToolResultMessage):
        if message.status in ("completed", "failed"):
            return message
        return None  # cancelled and interrupted: the completion rules give an "unfinished" result
    if isinstance(message, CustomMessage):
        if not message.for_model:
            return None
        return UserMessage(id=message.id, text=wrap_context(message.kind, message.for_model))
    return None


def _reason(state: SessionState, call_id: str) -> str:
    call: CallState | None = state.calls.get(call_id)
    if call is None:
        return strings.REASON_UNKNOWN

    result = state.result_of(call)
    if result is not None:
        if result.status == "interrupted":
            return strings.REASON_INTERRUPTED
        if result.status == "cancelled":
            return strings.REASON_UNANSWERED if result.error_code == "unanswered" else strings.REASON_STOPPED
        return strings.REASON_UNKNOWN

    turn = state.turns.get(call.turn_id or "")
    if turn is not None and turn.phase == "done":
        return strings.REASON_NOT_RUN
    return strings.REASON_UNKNOWN


def not_completed(call: ToolCall, reason: str) -> ToolResultMessage:
    text = strings.NOT_COMPLETED.format(reason=reason)
    return ToolResultMessage(
        tool_call_id=call.id, tool_name=call.name, text=text, error=text, error_code="not_completed"
    )


def normalize(messages: list[Message], reason: Callable[[str], str] | None = None) -> list[Message]:
    results: dict[str, Message] = {}
    called: set[str] = set()
    for message in messages:
        if isinstance(message, ToolResultMessage):
            results.setdefault(message.tool_call_id, message)
        elif isinstance(message, AssistantMessage):
            called.update(call.id for call in message.tool_calls)

    output: list[Message] = []
    placed: set[str] = set()
    for message in messages:
        if isinstance(message, ToolResultMessage):
            continue  # Results are always placed after their call

        output.append(message)

        if isinstance(message, AssistantMessage):
            for call in message.tool_calls:
                if call.id in placed:
                    continue

                placed.add(call.id)
                found = results.get(call.id)
                if found is not None:
                    output.append(found)
                else:
                    output.append(not_completed(call, reason(call.id) if reason else strings.REASON_UNKNOWN))

    return output
