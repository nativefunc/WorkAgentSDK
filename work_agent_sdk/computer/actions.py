from __future__ import annotations

from typing import Any

import work_agent_sdk.strings.computer as strings
from work_agent_sdk.core.actions import Action, ActionCatalog
from work_agent_sdk.host.screen.actions import ACTIONS, READ_ONLY

# Coordinates from the model are screenshot pixels; the framework converts them to real screen pixels before passing them to the executor
POINT = {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2}
MODIFIERS = {
    "type": "string",
    "description": strings.MODIFIERS,
}
CLICK_INPUT = {
    "type": "object",
    "properties": {
        "coordinate": {**POINT, "description": strings.COORDINATE},
        "text": MODIFIERS,
    },
}

SCHEMAS: dict[str, dict[str, Any]] = {
    "screenshot": {"type": "object", "properties": {}},
    "zoom": {
        "type": "object",
        "properties": {
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 4,
                "maxItems": 4,
                "description": strings.ZOOM_REGION,
            }
        },
        "required": ["region"],
    },
    "left_click": CLICK_INPUT,
    "right_click": CLICK_INPUT,
    "middle_click": CLICK_INPUT,
    "double_click": CLICK_INPUT,
    "triple_click": CLICK_INPUT,
    "left_click_drag": {
        "type": "object",
        "properties": {"start_coordinate": POINT, "coordinate": POINT, "text": MODIFIERS},
        "required": ["start_coordinate", "coordinate"],
    },
    "mouse_move": {"type": "object", "properties": {"coordinate": POINT}, "required": ["coordinate"]},
    "left_mouse_down": {"type": "object", "properties": {}},
    "left_mouse_up": {"type": "object", "properties": {}},
    "cursor_position": {"type": "object", "properties": {}},
    "scroll": {
        "type": "object",
        "properties": {
            "scroll_direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
            "scroll_amount": {"type": "integer", "description": strings.SCROLL_AMOUNT},
            "coordinate": POINT,
            "text": MODIFIERS,
        },
        "required": ["scroll_direction", "scroll_amount"],
    },
    "type": {
        "type": "object",
        "properties": {"text": {"type": "string", "description": strings.TYPE_TEXT}},
        "required": ["text"],
    },
    "key": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": strings.KEY_TEXT},
            "repeat": {"type": "integer", "description": strings.KEY_REPEAT},
        },
        "required": ["text"],
    },
    "hold_key": {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "duration": {"type": "number", "description": strings.DURATION},
        },
        "required": ["text", "duration"],
    },
    "wait": {
        "type": "object",
        "properties": {"duration": {"type": "number", "description": strings.DURATION}},
        "required": ["duration"],
    },
}


if tuple(SCHEMAS) != ACTIONS:
    raise RuntimeError("The computer action schema doesn't match the executor's action table")

COMPUTER = ActionCatalog(
    "computer",
    [
        Action(
            name,
            SCHEMAS[name],
            strings.ACTIONS[name],
            read_only=name in READ_ONLY,
        )
        for name in ACTIONS
    ],
)


def from_openai(action: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    kind = action.get("type")
    keys = action.get("keys") or []
    modifiers = "+".join(str(key).lower() for key in keys) if keys and kind != "keypress" else None

    def point() -> list[int]:
        return [int(action["x"]), int(action["y"])]

    if kind == "click":
        button = action.get("button", "left")
        member = {
            "left": "left_click",
            "right": "right_click",
            "wheel": "middle_click",
            "middle": "middle_click",
        }
        if button not in member:
            raise ValueError(f"Unsupported mouse button: {button}")

        args: dict[str, Any] = {"coordinate": point()}
        if modifiers:
            args["text"] = modifiers

        return member[button], args

    if kind == "double_click":
        args = {"coordinate": point()}
        if modifiers:
            args["text"] = modifiers
        return "double_click", args
    if kind == "move":
        return "mouse_move", {"coordinate": point()}
    if kind == "drag":
        path = []
        for item in action["path"]:
            if isinstance(item, dict):
                path.append([int(item["x"]), int(item["y"])])
            else:
                path.append([int(item[0]), int(item[1])])

        args = {"start_coordinate": path[0], "coordinate": path[-1]}
        if modifiers:
            args["text"] = modifiers

        return "left_click_drag", args

    if kind == "scroll":
        dx, dy = int(action.get("scroll_x") or 0), int(action.get("scroll_y") or 0)
        if abs(dy) >= abs(dx):
            direction, amount = ("down" if dy > 0 else "up"), dy
        else:
            direction, amount = ("right" if dx > 0 else "left"), dx

        # OpenAI gives pixel values; about 100 pixels equals one notch
        args = {
            "scroll_direction": direction,
            "scroll_amount": max(1, abs(amount) // 100),
            "coordinate": point(),
        }
        if modifiers:
            args["text"] = modifiers

        return "scroll", args

    if kind == "keypress":
        return "key", {"text": "+".join(str(key).lower() for key in keys)}
    if kind == "type":
        return "type", {"text": action.get("text", "")}
    if kind == "wait":
        return "wait", {"duration": 2}
    if kind == "screenshot":
        return "screenshot", {}
    raise ValueError(f"Unsupported action: {kind}")
