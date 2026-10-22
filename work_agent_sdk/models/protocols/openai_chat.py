from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

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
from work_agent_sdk.models.protocols.content import (
    as_user,
    data_url,
    effort_name,
    is_same_model,
    media_with_data,
    tool_result_text,
    unsupported_media_text,
)

AUDIO_FORMATS = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
}
STOP_REASONS = {
    "stop": "stop",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "length",
}
# chat.completions.create 可识别的参数，其他参数放入 extra_body
SDK_PARAMS = {
    "model",
    "messages",
    "stream",
    "stream_options",
    "tools",
    "max_tokens",
    "max_completion_tokens",
    "temperature",
    "top_p",
    "stop",
    "seed",
    "reasoning_effort",
    "response_format",
}
THINKING_FORMATS = ("openai", "enable_thinking", "thinking_type", "openrouter", "none")


def chat_body(
    model_name: str,
    request: ModelRequest,
    *,
    thinking_format: str,
    reasoning_in_history: bool,
    max_tokens_field: str,
    stream_usage: bool,
) -> dict[str, Any]:
    settings = request.settings
    body: dict[str, Any] = {
        "model": model_name,
        "stream": True,
        "messages": chat_messages(request, reasoning_in_history=reasoning_in_history),
    }
    if stream_usage:
        body["stream_options"] = {"include_usage": True}

    tools = chat_tools(request)
    if tools:
        body["tools"] = tools
    if request.max_tokens:
        body[max_tokens_field] = request.max_tokens

    optional = {
        "temperature": settings.temperature,
        "top_p": settings.top_p,
        "stop": settings.stop,
        "seed": settings.seed,
    }
    body.update({key: value for key, value in optional.items() if value is not None})

    if request.output_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "result", "schema": request.output_schema, "strict": True},
        }

    body.update(thinking_params(thinking_format, request))
    body.update(settings.extra_body)
    return body


def thinking_params(thinking_format: str, request: ModelRequest) -> dict[str, Any]:
    thinking_off = request.thinking == "off"
    effort = effort_name(request.thinking)
    if thinking_format == "openai":
        return {} if thinking_off else {"reasoning_effort": effort}
    if thinking_format == "enable_thinking":
        if thinking_off:
            return {"enable_thinking": False}
        return {"enable_thinking": True, "thinking_budget": request.thinking_budget}
    if thinking_format == "thinking_type":
        return {"thinking": {"type": "disabled" if thinking_off else "enabled"}}
    if thinking_format == "openrouter":
        return {} if thinking_off else {"reasoning": {"effort": effort}}
    return {}


def media_block(part: MediaPart) -> dict[str, Any] | None:
    if part.kind == "image":
        return {"type": "image_url", "image_url": {"url": data_url(part)}}
    if part.kind == "audio" and part.mime in AUDIO_FORMATS:
        audio = {"data": part.data, "format": AUDIO_FORMATS[part.mime]}
        return {"type": "input_audio", "input_audio": audio}
    if part.kind == "video":
        return {"type": "video_url", "video_url": {"url": data_url(part)}}
    return None


def media_or_note(part: MediaPart) -> dict[str, Any]:
    return media_block(part) or {"type": "text", "text": unsupported_media_text(part)}


def user_content(message: Message) -> str | list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for part in message.content:
        if isinstance(part, TextPart):
            blocks.append({"type": "text", "text": part.text})
        elif isinstance(part, MediaPart) and part.data:
            blocks.append(media_or_note(part))

    if all(block["type"] == "text" for block in blocks):
        return "\n".join(block["text"] for block in blocks)
    return blocks


def function_call(call: Any) -> dict[str, Any]:
    return {
        "id": call.id,
        "type": "function",
        "function": {
            "name": call.name,
            "arguments": json.dumps(call.args, ensure_ascii=False),
        },
    }


def assistant_message(message: Message, request: ModelRequest, reasoning_in_history: bool) -> dict[str, Any]:
    item: dict[str, Any] = {"role": "assistant", "content": message.text or None}
    if reasoning_in_history:
        reasoning = message.thinking_text if is_same_model(message, request.model) else ""
        if reasoning or message.tool_calls:
            item["reasoning_content"] = reasoning

    if message.tool_calls:
        item["tool_calls"] = [function_call(call) for call in message.tool_calls]

    return item


def chat_messages(request: ModelRequest, *, reasoning_in_history: bool = False) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    tool_media: list[dict[str, Any]] = []

    def flush_tool_media() -> None:
        if not tool_media:
            return

        note = {"type": "text", "text": "（工具返回的内容）"}
        items.append({"role": "user", "content": [note, *tool_media]})
        tool_media.clear()

    if request.system:
        items.append({"role": "system", "content": request.system})

    for original in request.messages:
        if original.role != "tool":
            flush_tool_media()

        message = as_user(original)
        if message.role == "user":
            items.append({"role": "user", "content": user_content(message) or ""})
        elif message.role == "assistant":
            item = assistant_message(message, request, reasoning_in_history)
            if item["content"] is None and "tool_calls" not in item:
                continue
            items.append(item)
        elif message.role == "tool":
            items.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": tool_result_text(message),
                }
            )

            for part in media_with_data(message):
                tool_media.append(media_or_note(part))

    flush_tool_media()
    return items


def chat_tools(request: ModelRequest) -> list[dict[str, Any]]:
    tools = []
    for tool in request.tools:
        function = {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["parameters"],
        }
        tools.append({"type": "function", "function": function})

    return tools


def chat_usage(usage: dict[str, Any]) -> Usage:
    prompt_details = usage.get("prompt_tokens_details") or {}
    completion_details = usage.get("completion_tokens_details") or {}
    cached = prompt_details.get("cached_tokens") or usage.get("prompt_cache_hit_tokens") or 0
    prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
    return Usage(
        input_tokens=prompt_tokens - cached,
        output_tokens=usage.get("completion_tokens") or usage.get("output_tokens") or 0,
        cache_read_tokens=cached,
        reasoning_tokens=completion_details.get("reasoning_tokens") or 0,
    )


class ChatStreamParser:
    def __init__(self, error_codes: Mapping[str, str]) -> None:
        self.error_codes = error_codes
        self.usage: Usage | None = None
        self.finish_reason: str | None = None
        self.call_slots: dict[int, tuple[int, str | None]] = {}
        self.next_slot = 0

    def feed(self, chunk: dict[str, Any]) -> list[Delta]:
        if chunk.get("error"):
            raise self._error(chunk["error"])

        deltas: list[Delta] = []

        if chunk.get("usage"):
            self.usage = chat_usage(chunk["usage"])

        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}

            if choice.get("finish_reason"):
                self.finish_reason = choice["finish_reason"]

            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            if reasoning:
                deltas.append(ThinkingDelta(text=reasoning))
            if delta.get("content"):
                deltas.append(TextDelta(text=delta["content"]))
            if delta.get("refusal"):
                deltas.append(TextDelta(text=delta["refusal"]))

            for position, tool_call in enumerate(delta.get("tool_calls") or []):
                function = tool_call.get("function") or {}
                slot = self._slot(tool_call.get("index", position), tool_call.get("id"))
                deltas.append(
                    ToolCallDelta(
                        index=slot,
                        id=tool_call.get("id"),
                        name=function.get("name"),
                        args=function.get("arguments") or "",
                    )
                )

        return deltas

    def finish(self) -> Finish:
        reason = self.finish_reason or "stop"
        if reason == "content_filter":
            raise ModelError("输出被内容审核拦截", code="content_filter")
        return Finish(stop_reason=STOP_REASONS.get(reason, "stop"), usage=self.usage)

    def _slot(self, index: int, call_id: str | None) -> int:
        # 部分服务的每个调用都用 index 0，此时按 id 区分
        slot = self.call_slots.get(index)
        if slot is None or (call_id and slot[1] and call_id != slot[1]):
            slot = (self.next_slot, call_id)
            self.next_slot += 1
            self.call_slots[index] = slot
        elif call_id and not slot[1]:
            self.call_slots[index] = (slot[0], call_id)

        return slot[0]

    def _error(self, error: Any) -> ModelError:
        text = error if isinstance(error, str) else json.dumps(error, ensure_ascii=False)
        codes, _, status = error_fields(error)
        return ModelError(f"接口返回错误：{text}", code=classify(status, codes, self.error_codes), status=status)
