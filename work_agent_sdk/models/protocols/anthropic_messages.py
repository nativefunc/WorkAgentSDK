from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import work_agent_sdk.models.deferred_tools as deferred_tools
from work_agent_sdk.core.actions import BROWSER_STATE
from work_agent_sdk.core.messages import MediaPart, Message, TextPart, Usage
from work_agent_sdk.models.base import (
    Delta,
    Finish,
    ModelRequest,
    TextDelta,
    ThinkingDelta,
    ToolCallDelta,
)
from work_agent_sdk.models.errors import ModelError, classify, error_fields
from work_agent_sdk.models.native_tools import (
    anthropic_toolset_entries,
    native_toolsets,
    split_name,
)
from work_agent_sdk.models.protocols.content import (
    append_merged,
    as_user,
    history_thinking,
    media_with_data,
    safe_call_id,
    tool_result_text,
    unsupported_media_text,
)

STOP_REASONS = {
    "end_turn": "stop",
    "tool_use": "tool_use",
    "max_tokens": "length",
    "stop_sequence": "stop",
    "pause_turn": "stop",
    "model_context_window_exceeded": "length",
}

CACHEABLE_BLOCKS = {"text", "image", "tool_use", "tool_result", "document"}


def mark_cache(body: dict[str, Any]) -> None:
    if isinstance(body.get("system"), str) and body["system"]:
        body["system"] = [{"type": "text", "text": body["system"], "cache_control": {"type": "ephemeral"}}]

    messages = body.get("messages") or []
    if not messages:
        return

    blocks = messages[-1].get("content")
    if isinstance(blocks, list):
        for block in reversed(blocks):
            if isinstance(block, dict) and block.get("type") in CACHEABLE_BLOCKS:
                block["cache_control"] = {"type": "ephemeral"}
                return


def media_block(part: MediaPart) -> dict[str, Any] | None:
    if part.kind != "image":
        return None
    source = {"type": "base64", "media_type": part.mime, "data": part.data}
    return {"type": "image", "source": source}


def media_or_note(part: MediaPart) -> dict[str, Any]:
    return media_block(part) or {"type": "text", "text": unsupported_media_text(part)}


def content_blocks(message: Message) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for part in message.content:
        if isinstance(part, TextPart) and part.text.strip():
            blocks.append({"type": "text", "text": part.text})
        elif isinstance(part, MediaPart) and part.data:
            blocks.append(media_or_note(part))
    return blocks


def assistant_blocks(message: Message, request: ModelRequest) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for part, original in history_thinking(message, request.model):
        if original and part.redacted:
            blocks.append({"type": "redacted_thinking", "data": part.signature})
        elif original:
            blocks.append({"type": "thinking", "thinking": part.text, "signature": part.signature})
        else:
            blocks.append({"type": "text", "text": part.text})

    for block in content_blocks(message):
        if block["type"] == "text":
            blocks.append(block)

    native = native_toolsets(request.model, "anthropic")
    for call in message.tool_calls:
        block = {"type": "tool_use", "id": safe_call_id(call.id), "name": call.name, "input": call.args}
        member = split_name(call.name, native)
        if member is not None:
            block["name"] = member[1]
            block["toolset_name"] = member[0]

        blocks.append(block)

    return blocks


def tool_result_block(
    message: Message, native: frozenset[str] = frozenset(), loaded: list[str] | None = None
) -> dict[str, Any]:
    if loaded:
        # tool_search 加载的工具：接口将引用展开为完整定义（定义位于 tools 中，并标记了 defer_loading）
        return {
            "type": "tool_result",
            "tool_use_id": safe_call_id(message.tool_call_id or ""),
            "content": [{"type": "tool_reference", "tool_name": name} for name in loaded],
        }

    content = [{"type": "text", "text": tool_result_text(message)}]
    for part in media_with_data(message):
        content.append(media_or_note(part))

    block: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": safe_call_id(message.tool_call_id or ""),
        "content": content,
    }
    member = split_name(message.tool_name or "", native)
    if member is not None:
        block["toolset_name"] = member[0]
        state = (message.data or {}).get(BROWSER_STATE) if isinstance(message.data, dict) else None
        if member[0] == "browser" and state and not message.error:
            content.append({"type": "browser_state", **state})

    if message.error:
        block["is_error"] = True

    return block


def anthropic_messages(request: ModelRequest) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    deferring = deferred_tools.uses_native_loading(request, "anthropic")
    for message in map(as_user, request.messages):
        if message.role == "user":
            append_merged(items, "user", content_blocks(message), "content")
        elif message.role == "assistant":
            append_merged(items, "assistant", assistant_blocks(message, request), "content")
        elif message.role == "tool":
            native = native_toolsets(request.model, "anthropic")
            loaded = deferred_tools.usable_loaded_tools(message, request) if deferring else None
            append_merged(items, "user", [tool_result_block(message, native, loaded)], "content")

    return items


def anthropic_tools(request: ModelRequest) -> list[dict[str, Any]]:
    deferring = deferred_tools.uses_native_loading(request, "anthropic")
    plain, toolsets = anthropic_toolset_entries(request.tools, native_toolsets(request.model, "anthropic"))
    functions = [function_entry(tool) for tool in plain]
    if deferring:
        # 附带全部可搜索的工具（不计入请求前缀，接口据此展开 tool_reference）
        functions += [{**function_entry(tool), "defer_loading": True} for tool in request.deferred_tools]

    return functions + toolsets


def function_entry(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "input_schema": tool["parameters"],
    }


def has_unsigned_tool_use(messages: list[dict[str, Any]]) -> bool:
    for message in reversed(messages):
        if message["role"] != "assistant":
            continue

        block_types = {block["type"] for block in message["content"]}
        has_tool_use = "tool_use" in block_types
        has_signed_thinking = bool(block_types & {"thinking", "redacted_thinking"})
        return has_tool_use and not has_signed_thinking

    return False


class AnthropicStreamParser:
    def __init__(self, error_codes: Mapping[str, str]) -> None:
        self.error_codes = error_codes
        self.tool_indexes: dict[int, int] = {}
        self.usage = Usage()
        self.stop_reason = "stop"

    def feed(self, event: dict[str, Any]) -> list[Delta]:
        event_type = event.get("type")
        if event_type == "error":
            error = event.get("error") or {}
            codes, message, status = error_fields(error)
            raise ModelError(f"{error.get('type')}: {message}", code=classify(status, codes, self.error_codes))
        if event_type == "message_start":
            usage = (event.get("message") or {}).get("usage") or {}
            self.usage = Usage(
                input_tokens=usage.get("input_tokens") or 0,
                output_tokens=usage.get("output_tokens") or 0,
                cache_read_tokens=usage.get("cache_read_input_tokens") or 0,
                cache_write_tokens=usage.get("cache_creation_input_tokens") or 0,
            )
            return []
        if event_type == "content_block_start":
            return self._block_start(event["index"], event["content_block"])
        if event_type == "content_block_delta":
            return self._block_delta(event["index"], event["delta"])
        if event_type == "message_delta":
            self._message_delta(event)

        return []

    def finish(self) -> Finish:
        return Finish(stop_reason=self.stop_reason, usage=self.usage)

    def _block_start(self, index: int, block: dict[str, Any]) -> list[Delta]:
        block_type = block["type"]
        if block_type == "tool_use":
            self.tool_indexes[index] = len(self.tool_indexes)
            call_index = self.tool_indexes[index]
            name = block.get("name")
            if block.get("toolset_name"):
                # 原生工具集的成员：转换回框架中的名称（如 computer_left_click）
                name = f"{block['toolset_name']}_{name}"

            return [ToolCallDelta(index=call_index, id=block.get("id"), name=name, args="")]

        if block_type == "redacted_thinking":
            return [ThinkingDelta(signature=block.get("data"), redacted=True, index=index)]
        if block_type == "thinking":
            return [ThinkingDelta(text=block.get("thinking") or "", index=index)]
        if block_type == "text" and block.get("text"):
            return [TextDelta(text=block["text"], index=index)]
        return []

    def _block_delta(self, index: int, delta: dict[str, Any]) -> list[Delta]:
        delta_type = delta["type"]
        if delta_type == "text_delta":
            return [TextDelta(text=delta["text"], index=index)]
        if delta_type == "thinking_delta":
            return [ThinkingDelta(text=delta["thinking"], index=index)]
        if delta_type == "signature_delta":
            return [ThinkingDelta(signature=delta["signature"], index=index)]
        if delta_type == "input_json_delta" and index in self.tool_indexes:
            return [ToolCallDelta(index=self.tool_indexes[index], args=delta["partial_json"])]
        return []

    def _message_delta(self, event: dict[str, Any]) -> None:
        reason = (event.get("delta") or {}).get("stop_reason") or ""
        if reason == "refusal":
            raise ModelError("模型拒绝回答（refusal）", code="content_filter")

        self.stop_reason = STOP_REASONS.get(reason, "stop")
        usage = event.get("usage") or {}
        if usage.get("output_tokens") is not None:
            self.usage.output_tokens = usage["output_tokens"]
