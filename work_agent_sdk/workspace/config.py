from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from work_agent_sdk.host.commands.sandbox import Sandbox


class Workspace(BaseModel):

    model_config = ConfigDict(extra="forbid")

    path: str
    node: str = "local"
    sandbox: Sandbox
    description: str = ""

    def __init__(self, path: str | None = None, /, **data: Any) -> None:
        if path is not None:
            data["path"] = path
        super().__init__(**data)

    @model_validator(mode="before")
    @classmethod
    def _require_sandbox(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("sandbox") is None:
            raise ValueError("The workspace needs a sandbox: sandbox=SRT(...) or NoSandbox()")
        return data

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        if value.strip() in ("", "/", "~", "~/"):
            raise ValueError("The workspace can't be the root directory or the user's home directory; specify a project directory")
        return value

    def to_config(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
