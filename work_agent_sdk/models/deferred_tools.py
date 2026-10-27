from __future__ import annotations

from typing import Any

from work_agent_sdk.core.messages import Message

TOOL_SEARCH = "tool_search"


def uses_native_loading(request: Any, style: str) -> bool:
    model = request.model
    return bool(
        request.deferred_tools
        and getattr(model, "native_tool_search", False)
        and getattr(model, "native_style", None) == style
    )


def usable_loaded_tools(message: Message, request: Any) -> list[str]:
    if getattr(message, "tool_name", None) != TOOL_SEARCH or getattr(message, "error", None):
        return []

    available = {tool["name"] for tool in request.deferred_tools}
    return [name for name in getattr(message, "loaded_tools", None) or [] if name in available]
