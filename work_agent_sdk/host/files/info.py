from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class FileInfo:
    """文件或目录的信息。real_path 为解析符号链接后的真实路径。"""

    path: str
    name: str
    is_dir: bool
    size: int
    modified: float
    mime: str | None
    real_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> FileInfo:
        return FileInfo(**data)
