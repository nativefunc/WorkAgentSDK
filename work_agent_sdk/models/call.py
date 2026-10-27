from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from work_agent_sdk.core.messages import (
    AssistantMessage,
    MediaPart,
    Message,
    TextPart,
    ThinkingPart,
    ToolCall,
    Usage,
    UserMessage,
)
from work_agent_sdk.core.utils import new_id
from work_agent_sdk.models.base import (
    Delta,
    Finish,
    Model,
    ModelRequest,
    ModelSettings,
    TextDelta,
    ThinkingDelta,
    ToolCallDelta,
)
from work_agent_sdk.models.errors import ModelError, backoff

MAX_RETRY_DELAY = 60.0
MEDIA_NAMES = {"image": "Image", "audio": "Audio", "video": "Video"}

DeltaCallback = Callable[[dict[str, Any]], Awaitable[None]]
RetryCallback = Callable[[Model, int, float, ModelError], Awaitable[None]]


def parse_tool_args(text: str) -> dict[str, Any] | None:
    """Parse the JSON text of tool arguments. Returns None when it isn't a JSON object."""
    if not text.strip():
        return {}

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None

    return value if isinstance(value, dict) else None


class _PendingCall:
    def __init__(self) -> None:
        self.id: str | None = None
        self.name = ""
        self.args_text = ""
        self.args: dict[str, Any] | None = None
        self.signature: str | None = None

    def to_tool_call(self, truncated: bool) -> ToolCall:
        args = self.args if self.args is not None else parse_tool_args(self.args_text)
        args_error = None
        if args is None:
            args = {}
            args_error = "truncated" if truncated else "invalid"

        return ToolCall(
            id=self.id or new_id("call_"),
            name=self.name,
            args=args,
            signature=self.signature,
            args_error=args_error,
        )


class MessageBuilder:
    def __init__(self) -> None:
        self.parts: list[TextPart | ThinkingPart] = []
        self.tool_calls: dict[int, _PendingCall] = {}
        self.usage: Usage | None = None
        self.stop_reason: str | None = None
        self.first_token_at: float | None = None
        self.thinking_started_at: float | None = None
        self.thinking_ended_at: float | None = None
        self._last_kind: str | None = None
        self._last_index: int | None = None

    @property
    def has_output(self) -> bool:
        return bool(self.tool_calls) or any(part.text for part in self.parts)

    def add(self, delta: Delta) -> dict[str, Any] | None:
        if isinstance(delta, (TextDelta, ThinkingDelta)):
            return self._add_text(delta)
        if isinstance(delta, ToolCallDelta):
            return self._add_tool_call(delta)
        if isinstance(delta, Finish):
            self.stop_reason = delta.stop_reason
            self.usage = delta.usage or self.usage
            return None
        raise TypeError(f"The model produced an unrecognized delta: {delta!r}")

    def content(self) -> list[TextPart | ThinkingPart]:
        content = []
        for part in self.parts:
            redacted = isinstance(part, ThinkingPart) and part.redacted
            if part.text or part.signature or redacted:
                content.append(part.model_copy())
        return content

    def message(self) -> AssistantMessage:
        truncated = self.stop_reason == "length"
        calls = [self.tool_calls[index].to_tool_call(truncated) for index in sorted(self.tool_calls)]
        stop_reason = self.stop_reason or "stop"
        if calls and stop_reason != "length":
            stop_reason = "tool_use"
        elif not calls and stop_reason == "tool_use":
            stop_reason = "stop"

        thinking_duration = None
        if self.thinking_started_at is not None:
            ended = self.thinking_ended_at or time.time()
            thinking_duration = round(ended - self.thinking_started_at, 3)

        return AssistantMessage(
            content=self.content(),
            tool_calls=calls,
            usage=self.usage or Usage(),
            stop_reason=stop_reason,
            thinking_duration=thinking_duration,
        )

    def _current_part(self, kind: str, index: int | None) -> TextPart | ThinkingPart:
        same_block = self._last_kind == kind and (index is None or index == self._last_index)
        if self.parts and same_block:
            return self.parts[-1]

        part: TextPart | ThinkingPart = ThinkingPart() if kind == "thinking" else TextPart(text="")
        self.parts.append(part)
        self._last_kind = kind
        self._last_index = index
        return part

    def _add_text(self, delta: TextDelta | ThinkingDelta) -> dict[str, Any] | None:
        thinking = isinstance(delta, ThinkingDelta)
        kind = "thinking" if thinking else "text"
        part = self._current_part(kind, delta.index)
        part.text += delta.text
        if delta.signature:
            part.signature = delta.signature
        if thinking and delta.redacted:
            part.redacted = True
        if not delta.text:
            return None

        self._mark_output(thinking)
        return {"kind": kind, "block": len(self.parts) - 1, "text": delta.text}

    def _add_tool_call(self, delta: ToolCallDelta) -> dict[str, Any]:
        call = self.tool_calls.setdefault(delta.index, _PendingCall())
        call.id = call.id or delta.id
        call.name = call.name or delta.name or ""
        call.signature = delta.signature or call.signature
        if isinstance(delta.args, dict):
            call.args = delta.args
            text = json.dumps(delta.args, ensure_ascii=False)
        else:
            call.args_text += delta.args
            text = delta.args

        self._mark_output(False)
        self._last_kind = "tool"
        self._last_index = None
        return {"kind": "tool_args", "index": delta.index, "name": delta.name, "text": text}

    def _mark_output(self, thinking: bool) -> None:
        moment = time.time()
        if self.first_token_at is None:
            self.first_token_at = moment

        if thinking:
            if self.thinking_started_at is None:
                self.thinking_started_at = moment
            self.thinking_ended_at = None
        elif self.thinking_started_at is not None and self.thinking_ended_at is None:
            self.thinking_ended_at = moment


def replace_unsupported_media(messages: list[Message], model: Model) -> list[Message]:
    converted = []
    for message in messages:
        if not message.media:
            converted.append(message)
            continue

        parts: list[Any] = []
        for part in message.content:
            if isinstance(part, MediaPart) and not model.accepts(part.kind):
                kind_name = MEDIA_NAMES.get(part.kind, part.kind)
                location = f", file at {part.path}" if part.path else ""
                parts.append(TextPart(text=f"[{kind_name}{location}. The current model can't view {kind_name.lower()} directly]"))
            else:
                parts.append(part)

        converted.append(message.model_copy(update={"content": parts}))

    return converted


class ModelCall:
    def __init__(
        self,
        request: ModelRequest,
        *,
        on_delta: DeltaCallback | None = None,
        on_retry: RetryCallback | None = None,
    ) -> None:
        self.request = request
        self.on_delta = on_delta
        self.on_retry = on_retry
        self.builder = MessageBuilder()
        self.attempts = 0
        self.model: Model = request.model
        self.started_at = time.time()

    async def run(self) -> AssistantMessage:
        return await self._run_one(self.model)

    async def _run_one(self, model: Model) -> AssistantMessage:
        request = await self._prepare(model)
        attempt = 0
        while True:
            attempt += 1
            self.attempts += 1
            self.builder = MessageBuilder()
            try:
                return await self._stream_once(model, request)
            except ModelError as model_error:
                # Only model API errors are retried; other exceptions (e.g. on_delta failing to write storage, framework bugs) are re-raised as is
                delay = self._retry_delay(model, model_error, attempt)
                if delay is None:
                    raise
                if self.on_retry is not None:
                    await self.on_retry(model, attempt, delay, model_error)

                await asyncio.sleep(delay)

    async def _prepare(self, model: Model) -> ModelRequest:
        messages = replace_unsupported_media(self.request.messages, model)
        system = self.request.system
        sent = self.request.model_copy(
            update={
                "model": model,
                "system": system,
                "thinking": model.thinking_level(self.request.thinking),
                "messages": messages,
            }
        )
        sent.ctx = self.request.ctx
        return sent

    async def _stream_once(self, model: Model, request: ModelRequest) -> AssistantMessage:
        async for delta in model.stream(request):
            update = self.builder.add(delta)
            if update is not None and self.on_delta is not None:
                await self.on_delta(update)

        message = self.builder.message()
        message.model = model.id
        return message

    def _retry_delay(self, model: Model, error: ModelError, attempt: int) -> float | None:
        # Don't retry once content has been output, to avoid duplicated content
        if self.builder.has_output or not error.retryable or attempt > model.max_retries:
            return None

        delay = error.retry_after if error.retry_after is not None else backoff(attempt, model.retry_delay)
        return None if delay > MAX_RETRY_DELAY else delay


async def generate(
    model: Model,
    prompt: str | list[Message],
    *,
    system: str = "",
    thinking: str = "off",
    settings: ModelSettings | None = None,
    output: type[BaseModel] | None = None,
    ctx: Any = None,
    on_finished: Callable[[ModelCall, float, BaseException | None], Awaitable[None]] | None = None,
) -> Any:
    messages = [UserMessage(text=prompt)] if isinstance(prompt, str) else list(prompt)
    request = ModelRequest(
        model=model,
        system=system,
        messages=messages,
        thinking=thinking,
        settings=settings or ModelSettings(),
    )
    if output is not None:
        schema = model.output_schema(output.model_json_schema())
        if schema is None:
            raise ModelError(f"{model.id} doesn't support structured output", code="bad_request")
        request.output_schema = schema

    request.ctx = ctx
    call = ModelCall(request)
    started = time.time()
    failure: BaseException | None = None
    try:
        message = await call.run()
    except BaseException as error:
        failure = error
        raise
    finally:
        if on_finished is not None:
            await on_finished(call, started, failure)

    if output is not None:
        return output.model_validate_json(message.text)
    return message.text
