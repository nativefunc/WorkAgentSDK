from __future__ import annotations

import copy
import json
from typing import Any

SCHEMA_KEYWORDS = ("properties", "items", "anyOf", "oneOf", "allOf", "prefixItems")


def adapt_schema(
    schema: dict[str, Any],
    *,
    closed: bool = False,
    all_required: bool = False,
    unsupported: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    result = copy.deepcopy(schema)
    for node in _walk(result):
        if closed and isinstance(node.get("additionalProperties"), dict):
            return None
        _move_unsupported(node, ("default", *unsupported))
        if closed and (node.get("type") == "object" or "properties" in node):
            node["additionalProperties"] = False
            if all_required:
                node["required"] = list(node.get("properties", {}))

    return result


def _walk(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if not isinstance(node, dict):
        return found

    found.append(node)

    for key in SCHEMA_KEYWORDS:
        value = node.get(key)
        if isinstance(value, dict) and key == "properties":
            for child in value.values():
                found.extend(_walk(child))
        elif isinstance(value, dict):
            found.extend(_walk(value))
        elif isinstance(value, list):
            for child in value:
                found.extend(_walk(child))

    for child in node.get("$defs", {}).values():
        found.extend(_walk(child))

    return found


def _move_unsupported(node: dict[str, Any], keywords: tuple[str, ...]) -> None:
    moved = {key: node.pop(key) for key in keywords if key in node}
    moved.pop("default", None)

    if not moved:
        return

    note = "；".join(f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in moved.items())
    description = node.get("description")
    node["description"] = f"{description}（{note}）" if description else f"（{note}）"
