from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from work_agent_sdk.host.commands.sandbox import Sandbox


class Workspace(BaseModel):
    """工作区：节点上的一个目录及其沙箱。节点本身是隔离边界时可不配置沙箱。工作区不提供传递环境变量的方式，命令所需的凭据应在节点上预先配置。"""

    model_config = ConfigDict(extra="forbid")

    path: str
    node: str = "local"
    sandbox: Sandbox | None = None
    description: str = ""

    def __init__(self, path: str | None = None, /, **data: Any) -> None:
        if path is not None:
            data["path"] = path
        super().__init__(**data)

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        if value.strip() in ("", "/", "~", "~/"):
            raise ValueError("工作区不能是根目录或家目录；请指定一个项目目录")
        return value

    def to_config(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
