from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import work_agent_sdk.models.deferred_tools as deferred_tools
from work_agent_sdk.core.messages import (
    MediaPart,
    Message,
    TextPart,
    ThinkingPart,
    Usage,
)
from work_agent_sdk.models.base import (
    Delta,
    Finish,
    ModelRequest,
    TextDelta,
    ThinkingDelta,
    ToolCallDelta,
)
from work_agent_sdk.models.deferred_tools import TOOL_SEARCH
from work_agent_sdk.models.errors import ModelError, classify, error_fields
from work_agent_sdk.models.native_tools import OPENAI_COMPUTER_TOOL, native_toolsets
from work_agent_sdk.models.protocols.content import (
    as_user,
    data_url,
    effort_name,
    is_same_model,
    media_with_data,
    tool_result_text,
    unsupported_media_text,
)

# Parameters recognized by responses.create; anything else goes into extra_body
SDK_PARAMS = {
    "model",
    "input",
    "stream",
    "store",
    "instructions",
    "tools",
    "max_output_tokens",
    "temperature",
    "top_p",
    "reasoning",
    "include",
    "text",
}


def responses_body(model_name: str, request: ModelRequest, *, reasoning_summary: str) -> dict[str, Any]:
    settings = request.settings
    body: dict[str, Any] = {
        "model": model_name,
        "input": responses_input(request),
        "stream": True,
        "store": False,
    }
    if request.system:
        body["instructions"] = request.system

    tools = responses_tools(request)
    if tools:
        body["tools"] = tools
    if request.max_tokens:
        body["max_output_tokens"] = request.max_tokens
    if settings.temperature is not None:
        body["temperature"] = settings.temperature
    if settings.top_p is not None:
        body["top_p"] = settings.top_p

    if request.thinking != "off":
        body["reasoning"] = {"effort": effort_name(request.thinking), "summary": reasoning_summary}
        body["include"] = ["reasoning.encrypted_content"]

    if request.output_schema is not None:
        body["text"] = {
            "format": {
                "type": "json_schema",
                "name": "result",
                "schema": request.output_schema,
                "strict": True,
            }
        }

    body.update(settings.extra_body)
    return body


def media_block(part: MediaPart) -> dict[str, Any] | None:
    if part.kind == "image":
        return {"type": "input_image", "image_url": data_url(part)}
    return None


def media_or_note(part: MediaPart) -> dict[str, Any]:
    return media_block(part) or {"type": "input_text", "text": unsupported_media_text(part)}


def user_content(message: Message) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for part in message.content:
        if isinstance(part, TextPart) and part.text:
            blocks.append({"type": "input_text", "text": part.text})
        elif isinstance(part, MediaPart) and part.data:
            blocks.append(media_or_note(part))
    return blocks


def reasoning_items(message: Message) -> list[dict[str, Any]]:
    items = []
    for part in message.content:
        if not isinstance(part, ThinkingPart) or not part.signature:
            continue
        try:
            item = json.loads(part.signature)
        except json.JSONDecodeError:
            continue
        if item.get("encrypted_content"):
            items.append(item)

    return items


def responses_input(request: ModelRequest) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    native = "computer" in native_toolsets(request.model, "openai")
    deferring = deferred_tools.uses_native_loading(request, "openai")
    for message in map(as_user, request.messages):
        if message.role == "user":
            content = user_content(message)
            if content:
                items.append({"role": "user", "content": content})
        elif message.role == "assistant":
            if is_same_model(message, request.model):
                items.extend(reasoning_items(message))
            if message.text:
                items.append({"role": "assistant", "content": message.text})

            for call in message.tool_calls:
                if deferring and call.name == TOOL_SEARCH:
                    items.append(
                        {
                            "type": "tool_search_call",
                            "call_id": call.id,
                            "execution": "client",
                            "status": "completed",
                            "arguments": call.args,
                        }
                    )
                    continue
                if native and call.name == OPENAI_COMPUTER_TOOL:
                    actions = call.args.get("actions") or []
                    items.append(
                        {
                            "type": "computer_call",
                            "call_id": call.id,
                            "actions": actions,
                            "status": "completed",
                        }
                    )
                    continue

                items.append(
                    {
                        "type": "function_call",
                        "call_id": call.id,
                        "name": call.name,
                        "arguments": json.dumps(call.args, ensure_ascii=False),
                    }
                )
        elif message.role == "tool" and native and message.tool_name == OPENAI_COMPUTER_TOOL:
            items.extend(computer_output(message))
        elif message.role == "tool" and deferring and message.tool_name == TOOL_SEARCH:
            items.extend(search_output(message, request))
        elif message.role == "tool":
            output: Any = tool_result_text(message)
            media = [media_or_note(part) for part in media_with_data(message)]
            if media:
                output = [{"type": "input_text", "text": output}, *media]

            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": output,
                }
            )

    return items


def computer_output(message: Message) -> list[dict[str, Any]]:
    images = [part for part in media_with_data(message) if part.kind == "image"]
    items: list[dict[str, Any]] = []
    if images:
        items.append(
            {
                "type": "computer_call_output",
                "call_id": message.tool_call_id,
                "output": {
                    "type": "computer_screenshot",
                    "image_url": data_url(images[-1]),
                    "detail": "original",
                },
            }
        )
    if message.error or not images:
        items.append({"role": "user", "content": [{"type": "input_text", "text": tool_result_text(message)}]})

    return items


def search_output(message: Message, request: ModelRequest) -> list[dict[str, Any]]:
    loaded = deferred_tools.usable_loaded_tools(message, request)
    by_name = {tool["name"]: tool for tool in request.deferred_tools}
    items: list[dict[str, Any]] = [
        {
            "type": "tool_search_output",
            "call_id": message.tool_call_id,
            "execution": "client",
            "status": "completed",
            "tools": [{**function_entry(by_name[name]), "defer_loading": True} for name in loaded],
        }
    ]
    if not loaded:
        items.append({"role": "user", "content": [{"type": "input_text", "text": tool_result_text(message)}]})

    return items


def function_entry(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": tool["parameters"],
    }


def responses_tools(request: ModelRequest) -> list[dict[str, Any]]:
    native = "computer" in native_toolsets(request.model, "openai")
    deferring = deferred_tools.uses_native_loading(request, "openai")
    tools: list[dict[str, Any]] = []

    # Loaded tools live in tool_search_output, not here, so the tool list doesn't change as tools are loaded
    for tool in request.tools:
        if native and tool["name"] == OPENAI_COMPUTER_TOOL:
            tools.append({"type": "computer"})
            continue
        if deferring and tool["name"] == TOOL_SEARCH:
            tools.append(
                {
                    "type": "tool_search",
                    "execution": "client",
                    "description": tool.get("description", ""),
                    "parameters": tool["parameters"],
                }
            )
            continue

        tools.append(function_entry(tool))

    return tools


def responses_usage(usage: dict[str, Any]) -> Usage:
    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    cached = input_details.get("cached_tokens") or 0
    return Usage(
        input_tokens=(usage.get("input_tokens") or 0) - cached,
        output_tokens=usage.get("output_tokens") or 0,
        cache_read_tokens=cached,
        reasoning_tokens=output_details.get("reasoning_tokens") or 0,
    )


class ResponsesStreamParser:
    def __init__(self, error_codes: Mapping[str, str]) -> None:
        self.error_codes = error_codes
        self.call_indexes: dict[int, int] = {}
        self.calls_with_args: set[int] = set()
        self.usage: Usage | None = None
        self.stop_reason = "stop"

    def feed(self, event: dict[str, Any]) -> list[Delta]:
        event_type = event.get("type", "")
        output_index = event.get("output_index") or 0
        if event_type == "response.output_item.added":
            return self._item_added(event["item"], output_index)
        if event_type in ("response.output_text.delta", "response.refusal.delta"):
            return [TextDelta(text=event["delta"], index=output_index)]
        if event_type in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
            return [ThinkingDelta(text=event["delta"], index=output_index)]
        if event_type == "response.reasoning_summary_part.added":
            if (event.get("summary_index") or 0) > 0:
                return [ThinkingDelta(text="\n\n", index=output_index)]
            return []
        if event_type == "response.function_call_arguments.delta":
            self.calls_with_args.add(output_index)
            return [ToolCallDelta(index=self._call_index(output_index), args=event["delta"])]
        if event_type == "response.function_call_arguments.done":
            if output_index in self.calls_with_args:
                return []

            self.calls_with_args.add(output_index)
            arguments = event.get("arguments") or ""
            return [ToolCallDelta(index=self._call_index(output_index), args=arguments)]
        if event_type == "response.output_item.done":
            return self._item_done(event["item"], output_index)
        if event_type in ("response.completed", "response.incomplete"):
            self._completed(event_type, event.get("response") or {})
            return []
        if event_type in ("response.failed", "error") or (not event_type and isinstance(event.get("error"), dict)):
            raise self._error(event)
        return []

    def finish(self) -> Finish:
        return Finish(stop_reason=self.stop_reason, usage=self.usage)

    def _call_index(self, output_index: int) -> int:
        if output_index not in self.call_indexes:
            self.call_indexes[output_index] = len(self.call_indexes)
        return self.call_indexes[output_index]

    def _item_added(self, item: dict[str, Any], output_index: int) -> list[Delta]:
        if item["type"] == "tool_search_call":
            return [
                ToolCallDelta(
                    index=self._call_index(output_index),
                    id=item.get("call_id"),
                    name=TOOL_SEARCH,
                    args="",
                )
            ]
        if item["type"] == "computer_call":
            return [
                ToolCallDelta(
                    index=self._call_index(output_index),
                    id=item.get("call_id"),
                    name=OPENAI_COMPUTER_TOOL,
                    args="",
                )
            ]
        if item["type"] != "function_call":
            return []
        return [
            ToolCallDelta(
                index=self._call_index(output_index),
                id=item.get("call_id"),
                name=item.get("name"),
                args="",
            )
        ]

    def _item_done(self, item: dict[str, Any], output_index: int) -> list[Delta]:
        if item["type"] == "reasoning":
            signature = json.dumps(item, ensure_ascii=False)
            return [ThinkingDelta(text="", signature=signature, index=output_index)]
        if item["type"] == "tool_search_call":
            arguments = item.get("arguments")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments or {}, ensure_ascii=False)

            return [
                ToolCallDelta(
                    index=self._call_index(output_index),
                    id=item.get("call_id"),
                    name=TOOL_SEARCH,
                    args=arguments,
                )
            ]
        if item["type"] == "computer_call":
            actions = item.get("actions") or ([item["action"]] if item.get("action") else [])
            arguments = json.dumps({"actions": actions}, ensure_ascii=False)
            return [
                ToolCallDelta(
                    index=self._call_index(output_index),
                    id=item.get("call_id"),
                    name=OPENAI_COMPUTER_TOOL,
                    args=arguments,
                )
            ]
        if item["type"] == "function_call" and output_index not in self.calls_with_args:
            self.calls_with_args.add(output_index)
            return [
                ToolCallDelta(
                    index=self._call_index(output_index),
                    id=item.get("call_id"),
                    name=item.get("name"),
                    args=item.get("arguments") or "",
                )
            ]
        return []

    def _completed(self, event_type: str, response: dict[str, Any]) -> None:
        self.usage = responses_usage(response.get("usage") or {})

        if event_type != "response.incomplete":
            return

        details = response.get("incomplete_details") or {}
        if details.get("reason") == "content_filter":
            raise ModelError("Output was blocked by content moderation", code="content_filter")

        self.stop_reason = "length"

    def _error(self, event: dict[str, Any]) -> ModelError:
        error = (event.get("response") or {}).get("error") or event.get("error") or event
        codes, message, status = error_fields(error)
        return ModelError(
            f"{error.get('code')}: {message}", code=classify(status, codes, self.error_codes), status=status
        )
