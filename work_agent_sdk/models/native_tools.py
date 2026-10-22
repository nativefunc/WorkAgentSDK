from __future__ import annotations

from typing import Any

ANTHROPIC_TOOLSETS = {"computer": "computer_toolset_20260801", "browser": "browser_toolset_20260801"}

COMPUTER_MEMBERS = (
    "screenshot", "zoom", "left_click", "right_click", "middle_click", "double_click", "triple_click",
    "left_click_drag", "mouse_move", "left_mouse_down", "left_mouse_up", "cursor_position", "scroll",
    "type", "key", "hold_key", "wait",
)  # fmt: skip
BROWSER_MEMBERS = (
    "navigate", "screenshot", "zoom", "left_click", "right_click", "middle_click", "double_click",
    "triple_click", "hover", "left_click_drag", "left_mouse_down", "left_mouse_up", "mouse_move", "scroll",
    "scroll_to", "type", "key", "hold_key", "wait", "read_page", "find", "get_page_text", "form_input",
    "file_upload", "read_console", "read_network", "javascript_exec", "new_tab", "list_tabs", "switch_tab",
    "close_tab",
)  # fmt: skip
MEMBERS = {"computer": COMPUTER_MEMBERS, "browser": BROWSER_MEMBERS}
# 原生工具集中默认关闭的成员：框架提供这些成员时需在 configs 中启用
DISABLED_BY_DEFAULT = {"browser": {"file_upload", "read_console", "read_network", "javascript_exec"}}

# OpenAI 的 computer 工具每次执行一组动作，对应 computer 工具集中名为 actions 的成员；工具名格式为 <工具集>_<成员>
OPENAI_COMPUTER_TOOL = "computer_actions"


def split_name(name: str, native: frozenset[str]) -> tuple[str, str] | None:
    for toolset in native:
        prefix = f"{toolset}_"
        if name.startswith(prefix) and name[len(prefix) :] in MEMBERS.get(toolset, ()):
            return toolset, name[len(prefix) :]
    return None


def anthropic_toolset_entries(tools: list[dict[str, Any]], native: frozenset[str]) -> tuple[list[dict], list[dict]]:
    plain: list[dict[str, Any]] = []
    members: dict[str, set[str]] = {}
    for tool in tools:
        toolset = tool.get("toolset")
        if toolset and toolset[0] in native and toolset[0] in ANTHROPIC_TOOLSETS:
            if toolset[1] in MEMBERS[toolset[0]]:
                members.setdefault(toolset[0], set()).add(toolset[1])
            continue
        plain.append(tool)

    entries = []
    for toolset, present in sorted(members.items()):
        entry: dict[str, Any] = {"type": ANTHROPIC_TOOLSETS[toolset]}
        configs = {member: {"enabled": False} for member in MEMBERS[toolset] if member not in present}
        for member in DISABLED_BY_DEFAULT.get(toolset, set()) & present:
            configs[member] = {"enabled": True}

        if configs:
            entry["configs"] = configs

        entries.append(entry)

    return plain, entries


def native_toolsets(model: Any, style: str) -> frozenset[str]:
    if getattr(model, "native_style", None) != style:
        return frozenset()
    return frozenset(getattr(model, "native_tools", ()) or ())
