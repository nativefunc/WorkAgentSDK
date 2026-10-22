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
    """拒绝。在 before_tool 中，message 返回给模型；在 before_turn 或 before_model 中，本轮以 rejected 结束。"""

    def __init__(self, message: str, *, code: str | None = None, data: Any = None) -> None:
        self.message = message
        self.code = code
        self.data = data

    def __repr__(self) -> str:
        return f"Deny({self.message!r}, code={self.code!r})"

    def error_info(self) -> ErrorInfo:
        return ErrorInfo(code=self.code or "denied", message=self.message, source="hook", data=self.data)


class Reply:
    """
    跳过当前步骤并直接给出结果：在 before_turn 中作为对用户的回答，在 before_model 中代替模型回答，
    在 before_tool 中代替工具结果。
    """

    def __init__(self, content: Any) -> None:
        self.content = content

    def __repr__(self) -> str:
        return f"Reply({self.content!r})"


class Continue:
    """在 before_turn_end 中返回，使模型继续工作；prompt 提供给模型。每轮最多 5 次。"""

    def __init__(self, prompt: str) -> None:
        if not prompt or not prompt.strip():
            raise ValueError("Continue 缺少 prompt；请提供给模型的提示")
        self.prompt = prompt.strip()

    def __repr__(self) -> str:
        return f"Continue({self.prompt!r})"


class Hooks:
    """钩子基类。方法名即介入点，只需实现所需的方法，未实现的介入点不生效。"""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name in vars(cls):
            if name.startswith(("before_", "after_", "on_")) and name not in HOOK_POINTS:
                raise TypeError(f"{cls.__name__}.{name} 不是有效的介入点；可用的介入点为 {'、'.join(HOOK_POINTS)}")

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
    """限定钩子仅对指定工具生效，例如 @only_tools("browser_*", "mcp__*")。"""

    def decorate(method: Callable) -> Callable:
        method.tool_patterns = patterns  # type: ignore[attr-defined]
        return method

    return decorate
