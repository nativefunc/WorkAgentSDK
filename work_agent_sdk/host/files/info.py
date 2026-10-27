from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class FileInfo:
    """Information about a file or directory. real_path is the real path after resolving symlinks."""

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
