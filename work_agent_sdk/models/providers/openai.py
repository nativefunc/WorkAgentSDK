from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from work_agent_sdk.models.base import Delta, ModelRequest
from work_agent_sdk.models.protocols.openai_chat import SDK_PARAMS as CHAT_PARAMS
from work_agent_sdk.models.protocols.openai_chat import (
    THINKING_FORMATS,
    ChatStreamParser,
    chat_body,
)
from work_agent_sdk.models.protocols.openai_responses import (
    SDK_PARAMS as RESPONSES_PARAMS,
)
from work_agent_sdk.models.protocols.openai_responses import (
    ResponsesStreamParser,
    responses_body,
)
from work_agent_sdk.models.schema import adapt_schema
from work_agent_sdk.models.sdk import SdkModel, import_sdk, split_params

APIS = ("responses", "chat")
# OpenAI error codes (error.code, then error.type); the same for the Responses and Chat Completions APIs
OPENAI_ERROR_CODES = {
    "rate_limit_exceeded": "rate_limit",
    "insufficient_quota": "quota",
    "context_length_exceeded": "context_overflow",
    "server_error": "server",
    "server_is_overloaded": "overloaded",
    "invalid_api_key": "auth",
}


class _OpenAISdkModel(SdkModel):
    def new_client(self, api_key: str | None) -> Any:
        openai = import_sdk("openai", "openai")
        return openai.AsyncOpenAI(
            api_key=api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=0,
        )

    def output_schema(self, schema: dict[str, Any]) -> dict[str, Any] | None:
        if not self.structured_output:
            return None
        return adapt_schema(schema, closed=True, all_required=True)

    async def _chat(self, request: ModelRequest, body: dict[str, Any]) -> AsyncIterator[Delta]:
        client = await self.sdk_client(request)
        params, extra = split_params(body, CHAT_PARAMS)
        headers = await self.request_headers(request)
        parser = ChatStreamParser(self.error_codes)
        events = self.events(
            client.chat.completions.create, **params, extra_body=extra or None, extra_headers=headers or None
        )
        async for chunk in events:
            for delta in parser.feed(chunk):
                yield delta

        yield parser.finish()


class OpenAI(_OpenAISdkModel):

    error_codes = OPENAI_ERROR_CODES

    def __init__(
        self,
        name: str,
        *,
        api: str = "responses",
        reasoning_summary: str = "auto",
        **options: Any,
    ) -> None:
        if api not in APIS:
            raise ValueError(f"Invalid api value; valid values are {APIS}")

        super().__init__(name, **options)

        if self.client is None:
            import_sdk("openai", "openai")

        self.api = api
        self.reasoning_summary = reasoning_summary

        # Only the Responses API provides the native computer tool; enable it with native_tools=("computer",)
        self.native_style = "openai" if api == "responses" else None

    def action_batches(self, toolset: str) -> bool:
        return self.native_style == "openai" and toolset in self.native_tools

    async def stream(self, request: ModelRequest) -> AsyncIterator[Delta]:
        if self.api == "chat":
            body = chat_body(
                self.name,
                request,
                thinking_format="openai",
                reasoning_in_history=False,
                max_tokens_field="max_completion_tokens",
                stream_usage=True,
            )
            async for delta in self._chat(request, body):
                yield delta

            return

        body = responses_body(self.name, request, reasoning_summary=self.reasoning_summary)
        client = await self.sdk_client(request)
        params, extra = split_params(body, RESPONSES_PARAMS)
        headers = await self.request_headers(request)
        parser = ResponsesStreamParser(self.error_codes)
        events = self.events(
            client.responses.create,
            **params,
            extra_body=extra or None,
            extra_headers=headers or None,
        )
        async for event in events:
            for delta in parser.feed(event):
                yield delta

        yield parser.finish()


class OpenAICompatible(_OpenAISdkModel):

    error_codes = {}

    thinking_format = "none"
    reasoning_in_history = False

    def __init__(
        self,
        name: str,
        *,
        thinking_format: str | None = None,
        reasoning_in_history: bool | None = None,
        max_tokens_field: str = "max_tokens",
        stream_usage: bool = True,
        **options: Any,
    ) -> None:
        super().__init__(name, **options)

        if self.client is None:
            if not self.base_url:
                raise ValueError(f"{type(self).__name__} is missing base_url; specify the provider's API address")
            import_sdk("openai", "openai")

        if thinking_format is not None:
            self.thinking_format = thinking_format
        if self.thinking_format not in THINKING_FORMATS:
            raise ValueError(f"Invalid thinking_format value; valid values are {THINKING_FORMATS}")
        if reasoning_in_history is not None:
            self.reasoning_in_history = reasoning_in_history

        self.max_tokens_field = max_tokens_field
        self.stream_usage = stream_usage

    async def stream(self, request: ModelRequest) -> AsyncIterator[Delta]:
        body = chat_body(
            self.name,
            request,
            thinking_format=self.thinking_format,
            reasoning_in_history=self.reasoning_in_history,
            max_tokens_field=self.max_tokens_field,
            stream_usage=self.stream_usage,
        )
        async for delta in self._chat(request, body):
            yield delta
