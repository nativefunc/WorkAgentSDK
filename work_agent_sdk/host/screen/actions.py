from __future__ import annotations

from typing import Any

ACTIONS = (
    "screenshot", "zoom", "left_click", "right_click", "middle_click", "double_click", "triple_click",
    "left_click_drag", "mouse_move", "left_mouse_down", "left_mouse_up", "cursor_position", "scroll",
    "type", "key", "hold_key", "wait",
)  # fmt: skip
READ_ONLY = frozenset({"screenshot", "zoom", "cursor_position", "wait"})

# click 级别只允许这些动作，且不带修饰键
POINTER = frozenset(
    {"left_click", "right_click", "middle_click", "double_click", "triple_click", "mouse_move", "scroll"}
)
KEYBOARD = frozenset({"type", "key", "hold_key"})
POINT_FIELDS = ("coordinate", "start_coordinate")


def is_input(action: str) -> bool:
    return action not in READ_ONLY


def key_parts(combination: str) -> list[str]:
    text = combination.strip()
    if text == "+":
        return ["+"]
    if text.endswith("++"):
        return [*[part for part in text[:-2].split("+") if part], "+"]
    return [part for part in text.split("+") if part]


SYSTEM_MODIFIERS = {"super", "cmd", "command", "meta", "win", "windows"}


def is_system_key(combination: str) -> bool:
    parts = [part.lower() for part in key_parts(combination)]
    if any(part in SYSTEM_MODIFIERS for part in parts):
        return True
    if "alt" in parts and any(part in ("tab", "f4", "escape", "esc") for part in parts):
        return True
    return "ctrl" in parts and "alt" in parts


def summarize_action(action: str, args: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for field in (
        "coordinate",
        "start_coordinate",
        "scroll_direction",
        "scroll_amount",
        "duration",
        "region",
    ):
        if args.get(field) is not None:
            summary[field] = args[field]

    if action == "type":
        summary["text_length"] = len(str(args.get("text") or ""))
    elif args.get("text"):
        summary["keys"] = str(args["text"])[:100]

    return summary
