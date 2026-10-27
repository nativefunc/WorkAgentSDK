from __future__ import annotations

import json
import re
from typing import Any

from work_agent_sdk import PendingRequest
from work_agent_sdk.core.messages import MediaPart, TextPart, ThinkingPart
from work_agent_sdk.events import (
    MessageCompleted,
    MessageStarted,
    MessageUpdated,
    QueueChanged,
    RequestClosed,
    RequestOpened,
    SessionRewound,
    TurnEnded,
    TurnStarted,
)

UPLOAD_PATH = re.compile(r"(?:^|/)uploads/(up_[0-9a-f]+)")
NOTE_PREFIX = "\u2063[openmuse] "
FILES_PREFIX = "\u2063[openmuse-files] "


def strip_notes(text: str) -> str:
    for prefix in (NOTE_PREFIX, FILES_PREFIX):
        index = text.find(prefix)
        if index >= 0:
            text = text[:index]
    return text.rstrip()


MAX_OUTPUT = 1500
MAX_DATA = 4000

PREVIEW_FIELDS = (
    "url",
    "command",
    "query",
    "question",
    "app",
    "path",
    "prompt",
    "name",
    "reason",
    "text",
)


def preview_args(name: str, args: dict[str, Any]) -> str:
    if name in ("browser_type", "computer_type") and isinstance(args.get("text"), str):
        return f"“{args['text'][:40]}”"
    for field in PREVIEW_FIELDS:
        value = args.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip().splitlines()[0][:120]
    if isinstance(args.get("coordinate"), list):
        return "at " + ", ".join(str(int(v)) for v in args["coordinate"][:2])
    return ""


def _clip(value: Any, limit: int = MAX_DATA) -> Any:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None
    if len(text) <= limit:
        return json.loads(text)
    return {"truncated": text[:limit]}


class Converter:
    def __init__(self) -> None:
        self.calls: dict[str, dict[str, str]] = {}

    def message(self, message: Any) -> dict[str, Any] | None:
        base = {
            "id": message.id,
            "role": message.role,
            "status": message.status,
            "created_at": message.created_at,
            "turn_id": message.turn_id,
        }
        role = message.role
        if role == "user":
            images = []
            files: list[dict[str, Any]] = []
            for part in message.content:
                if isinstance(part, MediaPart) and part.kind == "image":
                    match = UPLOAD_PATH.search(part.path or "")
                    images.append({"id": match.group(1) if match else None, "mime": part.mime})
                elif isinstance(part, TextPart) and part.text.startswith(FILES_PREFIX):
                    try:
                        files = json.loads(part.text[len(FILES_PREFIX) :])
                    except ValueError:
                        files = []
            return {**base, "text": message.text, "images": images, "files": files}

        if role == "assistant":
            calls = []
            for call in message.tool_calls:
                preview = preview_args(call.name, call.args)
                self.calls[call.id] = {"name": call.name, "preview": preview}
                calls.append({"id": call.id, "name": call.name, "preview": preview})
            thinking = any(isinstance(part, ThinkingPart) for part in message.content)
            return {
                **base,
                "text": message.text,
                "tool_calls": calls,
                "thinking": thinking,
                "error": message.error,
                "stop_reason": message.stop_reason,
            }

        if role == "tool":
            output = message.text
            return {
                **base,
                "tool": message.tool_name,
                "call_id": message.tool_call_id,
                "preview": self.calls.get(message.tool_call_id, {}).get("preview", ""),
                "output": output[:MAX_OUTPUT] + ("…" if len(output) > MAX_OUTPUT else ""),
                "has_image": any(isinstance(part, MediaPart) for part in message.content),
                "error": message.error,
                "error_code": message.error_code,
            }

        if role == "custom":
            if not message.display:
                return None
            return {**base, "kind": message.kind, "data": _clip(message.data), "text": message.for_model or ""}

        return None

    def events(self, event: Any) -> list[dict[str, Any]]:
        if isinstance(event, (MessageStarted, MessageCompleted)):
            item = self.message(event.message)
            return [{"type": "message", "message": item}] if item else []

        if isinstance(event, MessageUpdated):
            if event.message is not None:
                item = self.message(event.message)
                return [{"type": "message", "message": item}] if item else []
            if event.delta:
                kind = event.delta.get("kind")
                if kind == "text":
                    return [{"type": "delta", "id": event.message_id, "text": event.delta.get("text", "")}]
                if kind == "thinking":
                    return [{"type": "thinking", "id": event.message_id}]
                if "progress" in event.delta:
                    return [{"type": "progress", "id": event.message_id, "data": _clip(event.delta["progress"], 500)}]
                return []
            if event.changes:
                changes = {key: value for key, value in event.changes.items() if key in ("status", "display")}
                if "data" in event.changes:
                    changes["data"] = _clip(event.changes["data"])
                return [{"type": "patch", "id": event.message_id, "changes": changes}]
            return []

        if isinstance(event, RequestOpened):
            return [{"type": "request", "request": request(event.request)}]

        if isinstance(event, RequestClosed):
            return [
                {
                    "type": "request_closed",
                    "id": event.request_id,
                    "status": event.status,
                    "answer": _clip(event.answer, 1000),
                }
            ]

        if isinstance(event, TurnStarted):
            return [{"type": "turn", "state": "running", "turn_id": event.turn_id, "source": event.source}]

        if isinstance(event, TurnEnded):
            result = event.result
            error = None
            if result.error is not None:
                error = {"code": result.error.code, "message": result.error.message}
            return [{"type": "turn", "state": result.status, "turn_id": event.turn_id, "error": error}]

        if isinstance(event, QueueChanged):
            return [{"type": "queue", "count": len(event.items)}]

        if isinstance(event, SessionRewound):
            return [{"type": "reset"}]

        return []


def request(item: PendingRequest) -> dict[str, Any]:
    return {
        "id": item.id,
        "type": item.type,
        "data": _clip(item.data, 8000),
        "sensitive": item.sensitive,
        "call_id": item.call_id,
        "created_at": item.created_at,
    }
