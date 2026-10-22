from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

THINKING_LEVELS = ("off", "low", "medium", "high", "max")


@runtime_checkable
class ModelCapabilities(Protocol):
    id: str
    max_image_edge: int
    max_image_bytes: int
    screen_coordinates: tuple[int, int] | None
    structured_output_with_tools: bool

    @property
    def tool_search(self) -> bool: ...

    def accepts(self, kind: str) -> bool: ...

    def action_batches(self, toolset: str) -> bool: ...

    def output_schema(self, schema: dict[str, Any]) -> dict[str, Any] | None: ...

    def stream(self, request: Any) -> AsyncIterator[Any]: ...


__all__ = ["THINKING_LEVELS", "ModelCapabilities"]
