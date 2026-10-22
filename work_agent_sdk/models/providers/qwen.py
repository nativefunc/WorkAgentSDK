from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any

from work_agent_sdk.models.base import Delta, Model, ModelRequest
from work_agent_sdk.models.errors import ModelError, classify, to_model_error
from work_agent_sdk.models.protocols.openai_chat import (
    ChatStreamParser,
    chat_messages,
    chat_tools,
)
from work_agent_sdk.models.sdk import import_sdk, resolve_setting

# DashScope 的错误码（阿里云百炼文档）。输入超长与其他参数错误同为 InvalidParameter，按状态码报为 bad_request
DASHSCOPE_ERROR_CODES = {
    "InvalidApiKey": "auth",
    "invalid_api_key": "auth",
    "Throttling": "rate_limit",
    "Throttling.AllocationQuota": "quota",  # 免费额度用完（Free allocated quota exceeded），重试无效
    "Arrearage": "quota",
    "DataInspectionFailed": "content_filter",
    "data_inspection_failed": "content_filter",
    "CustomRoleBlocked": "content_filter",
    "FaqRuleBlocked": "content_filter",
}


class Qwen(Model):
    """通义千问。input_types 决定使用 Generation 还是 MultiModalConversation，两个接口支持的模型不同。"""

    error_codes = DASHSCOPE_ERROR_CODES
    # 请求中有工具时，DashScope 忽略 response_format，回答为普通文字
    structured_output_with_tools = False

    def __init__(
        self,
        name: str,
        *,
        api_key: str | Callable[..., Any] | None = "${DASHSCOPE_API_KEY}",
        base_url: str | None = None,
        headers: dict[str, str] | Callable[..., Any] | None = None,
        timeout: float = 600,
        **options: Any,
    ) -> None:
        # 千问视觉模型把图片视为 1000×1000，给出 0–1000 的相对坐标；按截图像素给出时截图越大偏差越多
        options.setdefault("screen_coordinates", (1000, 1000))
        super().__init__(name, **options)
        import_sdk("dashscope", "dashscope")
        self.api_key = api_key
        self.base_url = base_url
        self.headers = headers
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"Qwen({self.name!r}, {'MultiModalConversation' if self.multimodal else 'Generation'})"

    @property
    def multimodal(self) -> bool:
        return bool(self.input_types - {"text"})

    def request_params(self, request: ModelRequest) -> dict[str, Any]:
        settings = request.settings
        messages = chat_messages(request)
        params: dict[str, Any] = {
            "model": self.name,
            "messages": [multimodal_message(item) for item in messages]
            if self.multimodal
            else [text_message(item) for item in messages],
            "stream": True,
            "incremental_output": True,
            "result_format": "message",
        }
        tools = chat_tools(request)
        if tools:
            params["tools"] = tools
            params["parallel_tool_calls"] = True

        if request.output_schema is not None:
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "strict": True, "schema": request.output_schema},
            }
        if request.max_tokens:
            params["max_tokens"] = request.max_tokens

        optional = {
            "temperature": settings.temperature,
            "top_p": settings.top_p,
            "stop": settings.stop,
            "seed": settings.seed,
        }
        params.update({key: value for key, value in optional.items() if value is not None})

        if request.thinking == "off":
            params["enable_thinking"] = False
        else:
            params["enable_thinking"] = True
            params["thinking_budget"] = request.thinking_budget

        params.update(settings.extra_body)
        return params

    async def stream(self, request: ModelRequest) -> AsyncIterator[Delta]:
        dashscope = import_sdk("dashscope", "dashscope")
        api = dashscope.AioMultiModalConversation if self.multimodal else dashscope.AioGeneration
        api_key = await resolve_setting(self.api_key, request.ctx) if self.api_key is not None else None
        headers = await resolve_setting(self.headers, request.ctx) if self.headers is not None else {}
        headers = {**(headers or {}), **request.settings.extra_headers}
        connection: dict[str, Any] = {"api_key": api_key, "request_timeout": self.timeout}
        if self.base_url:
            connection["base_address"] = self.base_url
        if headers:
            connection["headers"] = headers

        parser = ChatStreamParser(self.error_codes)
        try:
            responses = await api.call(**self.request_params(request), **connection)
            async for response in responses:
                for delta in parser.feed(chat_chunk(response, self.error_codes)):
                    yield delta
        except ModelError:
            raise
        except Exception as error:
            converted = to_model_error(error, self.error_codes)
            if converted is None:
                raise
            raise converted from error

        yield parser.finish()


def text_message(item: dict[str, Any]) -> dict[str, Any]:
    content = item.get("content")
    if isinstance(content, list):
        item = {**item, "content": "\n".join(block.get("text", "") for block in content if block.get("type") == "text")}
    elif content is None:
        item = {**item, "content": ""}

    return item


def multimodal_message(item: dict[str, Any]) -> dict[str, Any]:
    if item["role"] == "tool":
        return item

    content = item.get("content")
    blocks: list[dict[str, Any]] = []
    if isinstance(content, str):
        if content:
            blocks.append({"text": content})
    elif isinstance(content, list):
        for block in content:
            kind = block.get("type")
            if kind == "text":
                blocks.append({"text": block["text"]})
            elif kind == "image_url":
                blocks.append({"image": block["image_url"]["url"]})
            elif kind == "video_url":
                blocks.append({"video": block["video_url"]["url"]})
            elif kind == "input_audio":
                audio = block["input_audio"]
                blocks.append({"audio": f"data:audio/{audio['format']};base64,{audio['data']}"})

    return {**item, "content": blocks}


def chat_chunk(response: Any, error_codes: Mapping[str, str]) -> dict[str, Any]:
    status = int(getattr(response, "status_code", 200) or 200)
    if status != 200:
        code = getattr(response, "code", "") or ""
        message = getattr(response, "message", "") or ""
        text = f"{code}: {message}".strip(": ")
        raise ModelError(f"接口返回错误：{text}", code=classify(status, [code], error_codes), status=status)

    output = _plain(getattr(response, "output", None)) or {}
    choices = []
    for choice in output.get("choices") or []:
        message = dict(choice.get("message") or {})
        content = message.get("content")
        if isinstance(content, list):  # MultiModalConversation 的回答同样为列表
            message["content"] = "".join(block.get("text", "") for block in content if isinstance(block, dict))

        finish = choice.get("finish_reason")
        choices.append({"delta": message, "finish_reason": None if finish in (None, "", "null") else finish})

    chunk: dict[str, Any] = {"choices": choices}
    usage = _plain(getattr(response, "usage", None))
    if usage:
        chunk["usage"] = {
            "prompt_tokens": usage.get("input_tokens") or 0,
            "completion_tokens": usage.get("output_tokens") or 0,
            "prompt_tokens_details": usage.get("prompt_tokens_details") or {},
            "completion_tokens_details": usage.get("output_tokens_details") or {},
        }

    return chunk


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "items"):
        return {key: _plain(item) for key, item in value.items()}
    return value
