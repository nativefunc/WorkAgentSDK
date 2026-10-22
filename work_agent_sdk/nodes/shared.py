from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

FOLDER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class SharedFolder(BaseModel):
    """name 为共享文件夹的名称；mounts 为 {节点名: 该节点上的路径}，路径可以 ~ 开头（指该节点的家目录）。"""

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
            raise ValueError(f"共享文件夹名称 {value!r} 不合法；仅允许字母、数字、- 和 _，最长 64 个字符")
        return value

    @field_validator("mounts")
    @classmethod
    def _mounts(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("共享文件夹至少需要一个节点上的路径")
        for node, path in value.items():
            if not path.strip():
                raise ValueError(f"共享文件夹在节点 {node} 上的路径为空")
        return value
