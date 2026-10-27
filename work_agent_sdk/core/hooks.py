from __future__ import annotations

from collections.abc import Callable
from typing import Any

from work_agent_sdk.core.errors import ErrorInfo
from work_agent_sdk.core.utils import matches_any

HOOK_POINTS = (
    "before_turn",
    "before_model",
    "after_model",
    "before_tool",
    "after_tool",
    "before_turn_end",
    "on_model_error",
)
MAX_CONTINUES = 5


class Deny:
    """Deny. In before_tool, message is returned to the model; in before_turn or before_model, the turn ends with rejected."""

    def __init__(self, message: str, *, code: str | None = None, data: Any = None) -> None:
        self.message = message
        self.code = code
        self.data = data

    def __repr__(self) -> str:
        return f"Deny({self.message!r}, code={self.code!r})"

    def error_info(self) -> ErrorInfo:
        return ErrorInfo(
            code=self.code or "denied",
            message=self.message,
            source="hook",
            data=self.data,
        )


class Reply:
    """
    Skip the current step and give a result directly: in before_turn it becomes the answer to the user, in before_model it replaces the model's response,
    and in before_tool it replaces the tool result.
    """

    def __init__(self, content: Any) -> None:
        self.content = content

    def __repr__(self) -> str:
        return f"Reply({self.content!r})"


class Continue:
    """Return from before_turn_end to make the model keep working; prompt is given to the model. At most 5 times per turn."""

    def __init__(self, prompt: str) -> None:
        if not prompt or not prompt.strip():
            raise ValueError("Continue is missing prompt; provide the prompt for the model")
        self.prompt = prompt.strip()

    def __repr__(self) -> str:
        return f"Continue({self.prompt!r})"


class Hooks:
    """Base class for hooks. Method names are the hook points; implement only the methods you need, and unimplemented hook points have no effect."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name in vars(cls):
            if name.startswith(("before_", "after_", "on_")) and name not in HOOK_POINTS:
                raise TypeError(f"{cls.__name__}.{name} is not a valid hook point; available hook points are {', '.join(HOOK_POINTS)}")

    def implements(self, point: str) -> bool:
        method = getattr(type(self), point, None)
        return method is not None and method is not getattr(Hooks, point, None)

    def applies_to(self, point: str, tool_name: str | None) -> bool:
        method = getattr(self, point)
        patterns = getattr(method, "tool_patterns", None)
        if not patterns or tool_name is None:
            return True
        return matches_any(tool_name, patterns)

    def __repr__(self) -> str:
        return type(self).__name__

    async def before_turn(self, ctx: Any, message: Any) -> Any:
        return None

    async def before_model(self, ctx: Any, request: Any) -> Any:
        return None

    async def after_model(self, ctx: Any, message: Any) -> Any:
        return None

    async def before_tool(self, ctx: Any, call: Any) -> Any:
        return None

    async def after_tool(self, ctx: Any, call: Any, result: Any) -> Any:
        return None

    async def before_turn_end(self, ctx: Any, message: Any) -> Any:
        return None

    async def on_model_error(self, ctx: Any, request: Any, error: Any) -> Any:
        return None


def only_tools(*patterns: str) -> Callable[[Callable], Callable]:
    """Restrict a hook to the given tools only, e.g. @only_tools("browser_*", "mcp__*")."""

    def decorate(method: Callable) -> Callable:
        method.tool_patterns = patterns  # type: ignore[attr-defined]
        return method

    return decorate
