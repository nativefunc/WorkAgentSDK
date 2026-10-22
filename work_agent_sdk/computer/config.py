from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from work_agent_sdk.host.screen.policy import ComputerPolicy


class Computer(BaseModel):
    """会话的电脑，即某个节点的屏幕。display 为 Linux X 桌面编号（如 ":1"）；policy 省略时为 standard()。"""

    model_config = ConfigDict(extra="forbid")

    node: str = "local"
    policy: ComputerPolicy = Field(default_factory=ComputerPolicy.standard)
    display: str | None = None
    description: str = ""

    def to_config(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
