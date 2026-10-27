from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorInfo(BaseModel):
    """Error information when a turn ends with an error or is rejected. source is model, tool, hook or internal."""

    code: str
    message: str
    source: str = "internal"
    retryable: bool = False
    data: Any = None


class ToolError(Exception):
    """An expected failure in a tool. message is returned to the model; code and data are provided to the frontend."""

    def __init__(self, message: str, *, code: str | None = None, data: Any = None, end_turn: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.data = data
        self.end_turn = end_turn


class ConfigError(ValueError):
    """Configuration error, raised when creating an Agent, Runner or session."""


class NodeOffline(Exception):
    """The node can't be reached."""

    def __init__(self, name: str, detail: str = "") -> None:
        super().__init__(f"Node {name} is currently offline{f': {detail}' if detail else ''}")
        self.name = name


class RequestClosed(Exception):
    """The request being answered is no longer waiting."""

    def __init__(self, request_id: str, status: str | None = None) -> None:
        super().__init__(f"Request {request_id} is no longer awaiting an answer{f' ({status})' if status else ''}")
        self.request_id = request_id
        self.status = status


class SessionClosed(Exception):
    """A message or answer was sent to a closed session."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Session {session_id} is closed")
        self.session_id = session_id


class InvalidAnswer(ValueError):
    """The answer doesn't match the request's answer_schema; the request keeps waiting."""


class TurnRejected(Exception):
    def __init__(self, info: ErrorInfo) -> None:
        super().__init__(info.message)
        self.info = info


class TurnFailed(Exception):
    def __init__(self, info: ErrorInfo) -> None:
        super().__init__(info.message)
        self.info = info


class HookFailed(Exception):
    def __init__(self, hook: str, point: str, error: BaseException) -> None:
        super().__init__(f"Hook {hook}.{point} failed: {type(error).__name__}: {error}")
        self.hook = hook
        self.point = point
        self.error = error
