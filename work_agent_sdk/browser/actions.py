from __future__ import annotations

from typing import Any

import work_agent_sdk.strings.browser as strings
from work_agent_sdk.core.actions import Action, ActionCatalog

TAB = {"type": "string", "description": strings.TAB_ID}
COORDINATE_TARGET = {
    "type": "object",
    "properties": {"type": {"const": "coordinate"}, "x": {"type": "integer"}, "y": {"type": "integer"}},
    "required": ["type", "x", "y"],
}
REF_TARGET = {
    "type": "object",
    "properties": {
        "type": {"const": "ref"},
        "ref": {"type": "string", "description": strings.REF},
    },
    "required": ["type", "ref"],
}
TARGET = {"anyOf": [COORDINATE_TARGET, REF_TARGET], "description": strings.TARGET}
MODIFIERS = {"type": "string", "description": strings.MODIFIERS}


def _object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": {**properties, "tab_id": TAB}}
    if required:
        schema["required"] = required
    return schema


_BROWSER_CLICK = _object({"target": TARGET, "modifiers": MODIFIERS}, ["target"])

_BROWSER_SCHEMAS: dict[str, dict[str, Any]] = {
    "navigate": _object({"url": {"type": "string", "description": strings.URL}}, ["url"]),
    "screenshot": _object({}),
    "zoom": _object(
        {
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 4,
                "maxItems": 4,
                "description": strings.ZOOM_REGION,
            }
        },
        ["region"],
    ),
    "left_click": _BROWSER_CLICK,
    "right_click": _BROWSER_CLICK,
    "middle_click": _BROWSER_CLICK,
    "double_click": _BROWSER_CLICK,
    "triple_click": _BROWSER_CLICK,
    "hover": _object({"target": TARGET}, ["target"]),
    "left_click_drag": _object({"from": COORDINATE_TARGET, "target": COORDINATE_TARGET}, ["from", "target"]),
    "left_mouse_down": _object({"target": COORDINATE_TARGET}, ["target"]),
    "left_mouse_up": _object({"target": COORDINATE_TARGET}, ["target"]),
    "mouse_move": _object({"target": COORDINATE_TARGET}, ["target"]),
    "scroll": _object(
        {
            "target": COORDINATE_TARGET,
            "scroll_direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
            "scroll_amount": {"type": "integer", "description": strings.SCROLL_AMOUNT},
        },
        ["target", "scroll_direction"],
    ),
    "scroll_to": _object({"target": REF_TARGET}, ["target"]),
    "type": _object({"text": {"type": "string"}}, ["text"]),
    "key": _object(
        {
            "text": {"type": "string", "description": strings.KEY_TEXT},
            "repeat": {"type": "integer"},
        },
        ["text"],
    ),
    "hold_key": _object({"text": {"type": "string"}, "duration": {"type": "number"}}, ["text", "duration"]),
    "wait": _object({"duration": {"type": "number", "description": strings.WAIT_DURATION}}, ["duration"]),
    "read_page": _object(
        {
            "filter": {
                "type": "string",
                "enum": ["interactive", "all"],
                "description": strings.READ_FILTER,
            },
            "depth": {"type": "integer"},
            "ref": {"type": "string", "description": strings.READ_REF},
        }
    ),
    "find": _object({"query": {"type": "string", "description": strings.FIND_QUERY}}, ["query"]),
    "get_page_text": _object({}),
    "form_input": _object(
        {"target": REF_TARGET, "value": {"type": ["string", "number", "boolean"]}}, ["target", "value"]
    ),
    "file_upload": _object(
        {
            "target": REF_TARGET,
            "paths": {"type": "array", "items": {"type": "string"}, "description": strings.UPLOAD_PATHS},
        },
        ["target", "paths"],
    ),
    "read_console": _object({}),
    "read_network": _object({}),
    "javascript_exec": _object({"text": {"type": "string", "description": strings.JAVASCRIPT}}, ["text"]),
    "new_tab": {"type": "object", "properties": {}},
    "list_tabs": {"type": "object", "properties": {}},
    "switch_tab": {"type": "object", "properties": {"tab_id": {"type": "string"}}, "required": ["tab_id"]},
    "close_tab": {"type": "object", "properties": {"tab_id": {"type": "string"}}, "required": ["tab_id"]},
}

_BROWSER_READ_ONLY = {
    "screenshot",
    "zoom",
    "read_page",
    "find",
    "get_page_text",
    "read_console",
    "read_network",
    "list_tabs",
    "wait",
}
_BROWSER_OPTIONAL = {"file_upload", "read_console", "read_network", "javascript_exec"}
_BROWSER_TABS = {"new_tab", "list_tabs", "switch_tab", "close_tab"}
# 读取页面内容的动作：执行前等待当前文档解析完成
_BROWSER_READS_PAGE = {"screenshot", "zoom", "read_page", "find", "get_page_text"}
# 执行后无需等待页面稳定的动作
_BROWSER_NO_SETTLE = {
    "screenshot",
    "zoom",
    "read_page",
    "find",
    "get_page_text",
    "read_console",
    "read_network",
    "javascript_exec",
    "wait",
}

BROWSER = ActionCatalog(
    "browser",
    [
        Action(
            name,
            schema,
            strings.ACTIONS[name],
            read_only=name in _BROWSER_READ_ONLY,
            optional=name in _BROWSER_OPTIONAL,
            settles=name not in _BROWSER_NO_SETTLE and name not in _BROWSER_TABS,
            reads_page=name in _BROWSER_READS_PAGE,
            tabs=name in _BROWSER_TABS,
        )
        for name, schema in _BROWSER_SCHEMAS.items()
    ],
)

# 用户接管浏览器时可由前端直接执行的动作（BoundBrowser.user_input，不经过模型）。
# switch_tab 由 user_input 自行处理，切换的是该会话的当前标签页
BROWSER_USER_INPUT = frozenset(
    {"left_click", "double_click", "right_click", "type", "key", "scroll", "navigate", "mouse_move", "switch_tab"}
)

KEY_NAMES = {
    "ctrl": "Control",
    "control": "Control",
    "cmd": "Meta",
    "command": "Meta",
    "super": "Meta",
    "meta": "Meta",
    "win": "Meta",
    "alt": "Alt",
    "option": "Alt",
    "shift": "Shift",
    "enter": "Enter",
    "return": "Enter",
    "esc": "Escape",
    "escape": "Escape",
    "backspace": "Backspace",
    "delete": "Delete",
    "tab": "Tab",
    "space": " ",
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "home": "Home",
    "end": "End",
}


def playwright_key(text: str) -> str:
    if text == "+":
        return "+"

    parts = [part for part in text.split("+") if part] or ["+"]
    return "+".join(KEY_NAMES.get(part.lower(), part) for part in parts)


def modifier_keys(text: str | None) -> list[str]:
    return [KEY_NAMES.get(part.lower(), part) for part in (text or "").split("+") if part]


def types_text(keys: str) -> bool:
    parts = [part for part in keys.split("+") if part]
    if not parts:
        return True

    *modifiers, key = parts
    if any(KEY_NAMES.get(name.lower(), name) in ("Control", "Meta", "Alt") for name in modifiers):
        return False
    return len(key) == 1 or key.lower() == "space"
