from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar

import work_agent_sdk.core.events as ev
from work_agent_sdk.core.messages import AssistantMessage, ToolResultMessage

if TYPE_CHECKING:
    from work_agent_sdk.runtime.sessions import Sessions

SUMMARY_CHARS = 500


def _summary(text: str) -> str:
    return text if len(text) <= SUMMARY_CHARS else text[:SUMMARY_CHARS] + "…"


class TurnTrace:
    def __init__(self, session_id: str, agent: str, turn_id: str) -> None:
        self.entry: dict[str, Any] = {
            "turn_id": turn_id,
            "session_id": session_id,
            "agent": agent,
            "source": None,
            "status": None,
            "segments": [],
            "started": None,
            "ended": None,
            "usage": None,
            "error": None,
            "items": [],
        }
        self.calls: dict[str, dict[str, Any]] = {}
        self.requests: dict[str, dict[str, Any]] = {}

    def call(self, call_id: str | None, ts: float, name: str = "", args: Any = None) -> dict[str, Any] | None:
        if not call_id:
            return None

        item = self.calls.get(call_id)
        if item is None:
            item = self.calls[call_id] = {
                "kind": "tool_call",
                "ts": ts,
                "call_id": call_id,
                "name": name,
                "args": args,
                "status": None,
                "ended": None,
                "duration": None,
                "error": None,
                "error_code": None,
                "result": None,
                "hooks": [],
                "steps": [],
                "requests": [],
                "subagents": [],
            }
            self.entry["items"].append(item)

        return item

    def add(self, event: ev.Event) -> None:
        handler = self.HANDLERS.get(type(event))
        if handler is not None:
            handler(self, event)

    def _turn_started(self, event: ev.TurnStarted) -> None:
        entry = self.entry
        if entry["started"] is None:
            entry["started"] = event.ts
            entry["source"] = event.source
        entry["segments"].append({"phase": event.phase, "started": event.ts, "ended": None, "status": None})

    def _turn_ended(self, event: ev.TurnEnded) -> None:
        entry = self.entry
        result = event.result
        entry["ended"] = event.ts
        entry["status"] = result.status
        usage = result.usage.model_dump()
        previous = entry["usage"] or {}
        entry["usage"] = {key: previous.get(key, 0) + value for key, value in usage.items()}
        entry["error"] = result.error.model_dump() if result.error else None
        if entry["segments"]:
            entry["segments"][-1].update(ended=event.ts, status=result.status)

    def _model_called(self, event: ev.ModelCalled) -> None:
        if event.call_id is None:
            self.entry["items"].append({"kind": "model_call", "ts": event.ts, **event.payload()})
            return

        item = self.calls.get(event.call_id)
        target = item["steps"] if item is not None else self.entry["items"]
        target.append({"kind": "generate", "ts": event.ts, **event.payload()})

    def _model_retried(self, event: ev.ModelRetried) -> None:
        self.entry["items"].append({"kind": "retry", "ts": event.ts, **event.payload()})

    def _message_started(self, event: ev.MessageStarted) -> None:
        message = event.message
        if isinstance(message, ToolResultMessage):
            item = self.call(message.tool_call_id, event.ts, message.tool_name)
            if item is not None:
                item["ts"] = event.ts

    def _message_completed(self, event: ev.MessageCompleted) -> None:
        message = event.message
        if isinstance(message, AssistantMessage):
            self._assistant_completed(message, event.ts)
        elif isinstance(message, ToolResultMessage):
            self._tool_result_completed(message, event.ts)

    def _assistant_completed(self, message: AssistantMessage, ts: float) -> None:
        for item in reversed(self.entry["items"]):
            if item["kind"] == "model_call" and "stop_reason" not in item:
                item["stop_reason"] = message.stop_reason
                item["text"] = _summary(message.text)
                break
        for call in message.tool_calls:
            self.call(call.id, ts, call.name, call.args)

    def _tool_result_completed(self, message: ToolResultMessage, ts: float) -> None:
        item = self.call(message.tool_call_id, ts, message.tool_name)
        if item is None:
            return

        result: dict[str, Any] = {"text": _summary(message.text)}
        images = [{"mime": part.mime, "data": part.data} for part in message.media if part.kind == "image"]
        if images:
            result["images"] = images
        if message.data is not None:
            result["data"] = message.data

        item.update(
            ended=ts,
            duration=round(ts - item["ts"], 3),
            status=message.status,
            error=message.error,
            error_code=message.error_code,
            result=result,
        )

    def _step_recorded(self, event: ev.StepRecorded) -> None:
        item = self.call(event.call_id, event.ts)
        if item is not None:
            item["steps"].append({"kind": "step", "ts": event.ts, "name": event.name})

    def _request_opened(self, event: ev.RequestOpened) -> None:
        request = {
            "ts": event.ts,
            "request_id": event.request.id,
            "type": event.request.type,
            "data": event.request.data,
            "status": "pending",
            "answer": None,
            "closed": None,
        }
        self.requests[event.request.id] = request
        item = self.call(event.request.call_id, event.ts)
        (item["requests"] if item is not None else self.entry["items"]).append(request)

    def _request_closed(self, event: ev.RequestClosed) -> None:
        request = self.requests.get(event.request_id)
        if request is not None:
            request.update(status=event.status, answer=event.answer, closed=event.ts)

    def _hook_applied(self, event: ev.HookApplied) -> None:
        hook = {"kind": "hook", "ts": event.ts, **event.payload()}
        item = self.call(event.call_id, event.ts)
        (item["hooks"] if item is not None else self.entry["items"]).append(hook)

    HANDLERS: ClassVar[dict[type[ev.Event], Callable[[TurnTrace, Any], None]]] = {
        ev.TurnStarted: _turn_started,
        ev.TurnEnded: _turn_ended,
        ev.ModelCalled: _model_called,
        ev.ModelRetried: _model_retried,
        ev.MessageStarted: _message_started,
        ev.MessageCompleted: _message_completed,
        ev.StepRecorded: _step_recorded,
        ev.RequestOpened: _request_opened,
        ev.RequestClosed: _request_closed,
        ev.HookApplied: _hook_applied,
    }


async def build_trace(sessions: Sessions, session_id: str, turn_id: str | None = None) -> list[dict[str, Any]]:
    worker = await sessions.worker(session_id)
    turns = await _turns(sessions, session_id, worker.record.agent)
    if turn_id is not None:
        turns = [turn for turn in turns if turn.entry["turn_id"] == turn_id]

    await _attach_children(sessions, session_id, turns)
    return [turn.entry for turn in turns]


async def _turns(sessions: Sessions, session_id: str, agent: str) -> list[TurnTrace]:
    builders: dict[str, TurnTrace] = {}
    for event in await sessions.core.store.events(session_id):
        if event.turn_id is None:
            continue

        builder = builders.get(event.turn_id)
        if builder is None:
            builder = builders[event.turn_id] = TurnTrace(session_id, agent, event.turn_id)

        builder.add(event)

    return sorted(builders.values(), key=lambda builder: builder.entry["started"] or 0)


async def _attach_children(sessions: Sessions, session_id: str, turns: list[TurnTrace]) -> None:
    calls = {call_id: item for turn in turns for call_id, item in turn.calls.items()}
    for child in await sessions.core.store.list_sessions(parent_id=session_id):
        parent_call = calls.get(child.parent_call_id or "")
        if parent_call is None:
            continue

        child_turns = await _turns(sessions, child.id, child.agent)
        parent_call["subagents"].extend(turn.entry for turn in child_turns)
