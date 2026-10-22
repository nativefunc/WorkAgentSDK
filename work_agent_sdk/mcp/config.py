from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from work_agent_sdk.core.utils import expand_env
from work_agent_sdk.mcp.oauth import OAuth

SERVER_NAME = re.compile(r"[A-Za-z0-9_\-]{1,40}")


class MCPServer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    auth: OAuth | None = None
    description: str | None = None
    trust_hints: bool = False
    resources: bool = False
    runs_on: Literal["runner", "workspace"] = "runner"
    # 默认在工作区的沙箱中运行。设为 True 时在沙箱外运行，配置了沙箱的设备上还需设备所有者启用 --allow-unsandboxed
    unsandboxed: bool = False
    timeout: float = 30
    tool_timeout: float = 600

    def __init__(self, name: str | None = None, /, **data: Any) -> None:
        if name is not None:
            data["name"] = name
        super().__init__(**data)

    @model_validator(mode="after")
    def _check(self) -> MCPServer:
        if not SERVER_NAME.fullmatch(self.name):
            raise ValueError(f"MCP 服务名称 {self.name!r} 不合法；仅允许字母、数字、- 和 _，最长 40 个字符")
        if bool(self.url) == bool(self.command):
            raise ValueError("MCP 服务须且仅须指定 url 或 command 之一")
        if self.runs_on == "workspace" and not self.command:
            raise ValueError('runs_on="workspace" 仅适用于以 command 启动的服务；请改用 command 或去掉 runs_on')
        if self.unsandboxed and self.runs_on != "workspace":
            raise ValueError('unsandboxed 仅适用于 runs_on="workspace" 的本地服务')
        if (self.headers or self.auth is not None) and not self.url:
            raise ValueError("headers 和 auth 仅适用于远程（url）服务；请改用 url 或去掉这两项")
        return self

    def oauth_target(self) -> tuple[OAuth, str]:
        if self.auth is None or not self.url:
            raise ValueError(f"MCP 服务 {self.name} 未配置 OAuth")
        return self.auth, self.url

    def resolved_headers(self) -> dict[str, str]:
        return {key: expand_env(value) for key, value in self.headers.items()}

    def resolved_env(self) -> dict[str, str]:
        return {key: expand_env(value) for key, value in self.env.items()}

    def connection_config(self) -> str:
        return MCPServer.model_dump_json(self)
