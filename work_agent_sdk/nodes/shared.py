from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

FOLDER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class SharedFolder(BaseModel):
    """name is the shared folder's name; mounts is {node name: path on that node}; paths may start with ~ (the user's home directory on that node)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    mounts: dict[str, str]

    def __init__(self, name: str | None = None, mounts: dict[str, str] | None = None, /, **data: Any) -> None:
        if name is not None:
            data["name"] = name
        if mounts is not None:
            data["mounts"] = mounts
        super().__init__(**data)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not FOLDER_NAME.match(value):
            raise ValueError(f"Invalid shared folder name {value!r}; only letters, digits, - and _ are allowed, up to 64 characters")
        return value

    @field_validator("mounts")
    @classmethod
    def _mounts(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("A shared folder needs a path on at least one node")
        for node, path in value.items():
            if not path.strip():
                raise ValueError(f"The shared folder's path on node {node} is empty")
        return value
