from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from work_agent_sdk.core.requests import Request


class AppAccess(Request):
    """The model requests to operate apps on the computer (applies to ComputerPolicy.standard). Each item in apps is {id, name, exe, tier, warning}."""

    reason: str
    apps: list[dict[str, Any]] = Field(default_factory=list)
    system_keys: bool = False

    class Answer(BaseModel):
        approved: bool
        note: str = ""
