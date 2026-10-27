from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from work_agent_sdk.core.errors import ErrorInfo
from work_agent_sdk.core.messages import Usage
from work_agent_sdk.core.requests import PendingRequest

TurnStatus = Literal["completed", "waiting", "stopped", "error", "rejected", "cancelled"]
TaskMode = Literal["foreground", "background", "detached"]


class TurnResult(BaseModel):
    """The result of a turn. When status is waiting the turn is paused, pending holds the requests awaiting answers, and the turn continues once they are answered."""

    turn_id: str = ""
    status: TurnStatus = "completed"
    text: str = ""
    data: Any = None
    pending: list[PendingRequest] = Field(default_factory=list)
    error: ErrorInfo | None = None
    usage: Usage = Field(default_factory=Usage)

    @property
    def final(self) -> bool:
        return self.status != "waiting"


class TaskResult(BaseModel):
    """The conclusion a child session submits to its parent session."""

    task_id: str
    agent: str
    status: Literal["completed", "error", "rejected", "stopped", "cancelled"] = "completed"
    text: str = ""
    data: Any = None
    error: ErrorInfo | None = None

    def for_model(self) -> dict[str, Any]:
        """Content for the parent model: the subagent's answer as is, plus data when output is set, plus an error when it didn't finish."""
        report: dict[str, Any] = {
            "agent": self.agent,
            "id": self.task_id,
            "status": self.status,
            "text": self.text,
        }
        if self.data is not None:
            report["data"] = self.data
        if self.error is not None:
            report["error"] = {"code": self.error.code, "message": self.error.message}

        return report


class TaskConfig(BaseModel):
    mode: TaskMode = "foreground"
    tools: list[str] | None = None


class SessionConfig(BaseModel):
    resources: dict[str, dict[str, Any]] = Field(default_factory=dict)
    model: str | None = None
    thinking: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    task: TaskConfig | None = None
    forked_from: str | None = None


class SessionRecord(BaseModel):
    id: str
    agent: str
    parent_id: str | None = None
    parent_call_id: str | None = None
    root_id: str
    status: Literal["open", "closed"] = "open"
    outcome: str | None = None
    config: SessionConfig = Field(default_factory=SessionConfig)
    created_at: float = 0.0
    updated_at: float = 0.0


class SessionInfo(BaseModel):
    id: str
    agent: str
    parent_id: str | None = None
    root_id: str
    status: str
    outcome: str | None = None
    created_at: float
    updated_at: float
    model: str | None = None
    thinking: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    resources: list[str] = Field(default_factory=list)
    activity: Literal["idle", "running", "waiting"] = "idle"
    queued: int = 0
    task: TaskConfig | None = None
