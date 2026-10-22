from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from work_agent_sdk.core.requests import Request


class AppAccess(Request):
    """模型申请操作电脑上的应用（适用于 ComputerPolicy.standard）。apps 的每一项为 {id, name, exe, tier, warning}。"""

    reason: str
    apps: list[dict[str, Any]] = Field(default_factory=list)
    system_keys: bool = False

    class Answer(BaseModel):
        approved: bool
        note: str = ""
