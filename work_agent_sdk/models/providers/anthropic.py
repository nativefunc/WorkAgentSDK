from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from work_agent_sdk.models.base import Delta, ModelRequest
from work_agent_sdk.models.protocols.anthropic_messages import (
    AnthropicStreamParser,
    anthropic_messages,
    anthropic_tools,
    has_unsigned_tool_use,
    mark_cache,
)
from work_agent_sdk.models.schema import adapt_schema
from work_agent_sdk.models.sdk import SdkModel, import_sdk, split_params

ANTHROPIC_UNSUPPORTED = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
)
MIN_ANSWER_TOKENS = 1024
MIN_THINKING_BUDGET = 1024
# Parameters recognized by messages.create; anything else goes into extra_body
SDK_PARAMS = {
    "model",
    "messages",
    "max_tokens",
    "stream",
    "system",
    "tools",
    "stop_sequences",
    "thinking",
    "temperature",
    "top_p",
}
THINKING_MODES = ("budget", "adaptive", "none")
# Anthropic error types (error.type). Context overflow and insufficient balance are both invalid_request_error with no dedicated type,
# so they're reported as bad_request by status code
ANTHROPIC_ERROR_CODES = {
    "overloaded_error": "overloaded",
    "rate_limit_error": "rate_limit",
    "api_error": "server",
    "authentication_error": "auth",
    "permission_error": "auth",
}


class Claude(SdkModel):

    native_style = "anthropic"
    error_codes = ANTHROPIC_ERROR_CODES

    def __init__(
        self,
        name: str,
        *,
        thinking_mode: str = "budget",
        default_max_tokens: int = 8192,
        cache: bool = True,
        **options: Any,
    ) -> None:
        if thinking_mode not in THINKING_MODES:
            raise ValueError(f"Invalid thinking_mode value; valid values are {THINKING_MODES}")

        # Computer and browser use native toolsets by default; pass native_tools=() for older models that don't support them
        options.setdefault("native_tools", ("computer", "browser"))
        super().__init__(name, **options)

        if self.client is None:
            import_sdk("anthropic", "anthropic")

        self.thinking_mode = thinking_mode
        self.default_max_tokens = default_max_tokens

        # Prompt caching: set cache breakpoints on the system prompt and the last message (content sent to the model is only appended at the end, so the prefix keeps hitting the cache)
        self.cache = cache

    def new_client(self, api_key: str | None) -> Any:
        anthropic = import_sdk("anthropic", "anthropic")
        return anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=0,
        )

    def output_schema(self, schema: dict[str, Any]) -> dict[str, Any] | None:
        if not self.structured_output:
            return None
        return adapt_schema(schema, closed=True, unsupported=ANTHROPIC_UNSUPPORTED)

    def build_body(self, request: ModelRequest) -> dict[str, Any]:
        settings = request.settings
        messages = anthropic_messages(request)
        max_tokens = request.max_tokens or self.default_max_tokens
        body: dict[str, Any] = {
            "model": self.name,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if request.system:
            body["system"] = request.system
        if self.cache:
            mark_cache(body)

        tools = anthropic_tools(request)
        if tools:
            body["tools"] = tools
        if settings.stop:
            body["stop_sequences"] = settings.stop

        thinking = self._add_thinking(body, request, messages)

        if request.output_schema is not None:
            output_config = body.setdefault("output_config", {})
            output_config["format"] = {"type": "json_schema", "schema": request.output_schema}

        if not thinking:
            if settings.temperature is not None:
                body["temperature"] = settings.temperature
            if settings.top_p is not None:
                body["top_p"] = settings.top_p

        body.update(settings.extra_body)
        return body

    def _add_thinking(self, body: dict[str, Any], request: ModelRequest, messages: list[dict[str, Any]]) -> bool:
        # If the previous tool call had no signed thinking, thinking can't be enabled for this one either (API requirement)
        if request.thinking == "off" or self.thinking_mode == "none":
            return False
        if has_unsigned_tool_use(messages):
            return False
        if self.thinking_mode == "adaptive":
            body["thinking"] = {"type": "adaptive"}
            body.setdefault("output_config", {})["effort"] = request.thinking
            return True

        budget = request.thinking_budget
        if request.max_tokens:
            budget = min(budget, body["max_tokens"] - MIN_ANSWER_TOKENS)
        else:
            body["max_tokens"] = max(body["max_tokens"], budget + MIN_ANSWER_TOKENS)

        if budget < MIN_THINKING_BUDGET:
            return False

        body["thinking"] = {"type": "enabled", "budget_tokens": budget}
        return True

    async def stream(self, request: ModelRequest) -> AsyncIterator[Delta]:
        body = self.build_body(request)
        client = await self.sdk_client(request)
        params, extra = split_params(body, SDK_PARAMS)
        headers = await self.request_headers(request)
        parser = AnthropicStreamParser(self.error_codes)
        events = self.events(
            client.messages.create,
            **params,
            extra_body=extra or None,
            extra_headers=headers or None,
        )
        async for event in events:
            for delta in parser.feed(event):
                yield delta

        yield parser.finish()
