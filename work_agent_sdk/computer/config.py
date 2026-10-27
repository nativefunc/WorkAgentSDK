from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from work_agent_sdk.host.screen.policy import ComputerPolicy


class Computer(BaseModel):
    """The session's computer, i.e. the screen of a node. display is the Linux X display number (e.g. ":1"); policy defaults to standard() when omitted."""

    model_config = ConfigDict(extra="forbid")

    node: str = "local"
    policy: ComputerPolicy = Field(default_factory=ComputerPolicy.standard)
    display: str | None = None
    description: str = ""

    def to_config(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
