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
    # Runs in the workspace sandbox by default. When True it runs outside the sandbox; on devices with a sandbox, the device owner must also enable --allow-unsandboxed
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
            raise ValueError(f"Invalid MCP server name {self.name!r}; only letters, digits, - and _ are allowed, up to 40 characters")
        if bool(self.url) == bool(self.command):
            raise ValueError("An MCP server must specify exactly one of url or command")
        if self.runs_on == "workspace" and not self.command:
            raise ValueError('runs_on="workspace" only applies to servers started with command; use command or remove runs_on')
        if self.unsandboxed and self.runs_on != "workspace":
            raise ValueError('unsandboxed only applies to local servers with runs_on="workspace"')
        if (self.headers or self.auth is not None) and not self.url:
            raise ValueError("headers and auth only apply to remote (url) servers; use url or remove these two")
        return self

    def oauth_target(self) -> tuple[OAuth, str]:
        if self.auth is None or not self.url:
            raise ValueError(f"MCP server {self.name} has no OAuth configured")
        return self.auth, self.url

    def resolved_headers(self) -> dict[str, str]:
        return {key: expand_env(value) for key, value in self.headers.items()}

    def resolved_env(self) -> dict[str, str]:
        return {key: expand_env(value) for key, value in self.env.items()}

    def connection_config(self) -> str:
        return MCPServer.model_dump_json(self)
