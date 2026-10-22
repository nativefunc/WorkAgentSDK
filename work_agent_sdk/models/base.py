from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from work_agent_sdk.core.messages import Message, Usage
from work_agent_sdk.core.model import THINKING_LEVELS

THINKING_BUDGETS = {"low": 2048, "medium": 8192, "high": 24576, "max": 32768}


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: list[str] | None = None
    seed: int | None = None
    thinking_budget: int | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)
    extra_headers: dict[str, str] = Field(default_factory=dict)


class ModelRequest(BaseModel):
    """一次模型请求。before_model 钩子可修改该请求，包括将 model 替换为其他模型对象。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: Any = None
    system: str = ""
    messages: list[Message] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    # 延后加载的扩展工具（runner.extensions），仅在模型使用 tool_search 时提供，由接口原生的方式加载
    deferred_tools: list[dict[str, Any]] = Field(default_factory=list)
    thinking: str = "off"
    settings: ModelSettings = Field(default_factory=ModelSettings)
    output_schema: dict[str, Any] | None = None
    ctx: Any = Field(default=None, exclude=True)

    @field_serializer("model")
    def _serialize_model(self, model: Any) -> Any:
        return model.id if isinstance(model, Model) else model

    @property
    def max_tokens(self) -> int | None:
        if self.settings.max_tokens:
            return self.settings.max_tokens
        if isinstance(self.model, Model):
            return self.model.max_output_tokens
        return None

    @property
    def thinking_budget(self) -> int:
        if self.settings.thinking_budget:
            return self.settings.thinking_budget
        return THINKING_BUDGETS.get(self.thinking, THINKING_BUDGETS["medium"])


class TextDelta(BaseModel):
    text: str
    signature: str | None = None
    index: int | None = None


class ThinkingDelta(BaseModel):
    text: str = ""
    signature: str | None = None
    redacted: bool = False
    index: int | None = None


class ToolCallDelta(BaseModel):
    """将同一 index 的增量合并为一个调用。args 可分段给出字符串，也可一次给出完整的 dict。"""

    index: int = 0
    id: str | None = None
    name: str | None = None
    args: str | dict[str, Any] = ""
    signature: str | None = None


class Finish(BaseModel):
    stop_reason: str = "stop"
    usage: Usage | None = None


Delta = TextDelta | ThinkingDelta | ToolCallDelta | Finish


class Model:
    """模型服务的协议适配基类。接入自定义服务时继承此类并实现 stream(request)。"""

    # 厂商错误码到错误类别的映射，如 {"overloaded_error": "overloaded"}；表中没有的按 HTTP 状态码归类
    error_codes: ClassVar[Mapping[str, str]] = {}
    # 原生结构化输出能否与工具同时使用。千问在请求带工具时忽略 response_format，这类模型改用 submit_result 工具
    structured_output_with_tools: ClassVar[bool] = True

    def __init__(
        self,
        name: str,
        *,
        id: str | None = None,
        input_types: Iterable[str] = ("text", "image"),
        context_window: int = 128_000,
        max_output_tokens: int | None = None,
        thinking_levels: Iterable[str] | None = None,
        structured_output: bool = False,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        native_tools: Iterable[str] = (),
        native_tool_search: bool = True,
        max_image_edge: int = 2048,
        max_image_bytes: int = 5_000_000,
        screen_coordinates: tuple[int, int] | None = None,
    ) -> None:
        self.name = name
        self.id = id or name
        self.input_types = frozenset(input_types)
        self.context_window = context_window
        self.max_output_tokens = max_output_tokens
        self.thinking_levels = list(thinking_levels) if thinking_levels is not None else None
        self.structured_output = structured_output
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # 以厂商原生格式发送的工具集："computer"、"browser"
        self.native_tools = frozenset(native_tools)

        # 扩展工具是否用厂商原生的延后加载（Claude 的 defer_loading、OpenAI Responses 的 tool_search）；
        # 旧模型不支持时传 False
        self.native_tool_search = native_tool_search

        # 框架自己产生的图片（电脑截图、ViewImage）缩放到此最长边以内
        self.max_image_edge = max_image_edge

        # 单张图片的上限（base64 后的字节数）。超限的图片不写入记录，否则之后每次调用模型都会被拒绝
        self.max_image_bytes = max_image_bytes

        # 模型给出屏幕坐标时的坐标系（宽, 高）。None 为截图像素；(1000, 1000) 表示 0–1000 的相对坐标
        self.screen_coordinates = (
            (int(screen_coordinates[0]), int(screen_coordinates[1])) if screen_coordinates else None
        )

    # 原生工具集的格式："anthropic"、"openai"，或 None（无原生格式，全部使用普通工具）
    native_style: str | None = None

    @property
    def tool_search(self) -> bool:
        return bool(self.native_tool_search and self.native_style in ("anthropic", "openai"))

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.id!r})"

    def accepts(self, kind: str) -> bool:
        return kind in self.input_types

    def action_batches(self, toolset: str) -> bool:
        return False

    def thinking_level(self, requested: str | None) -> str:
        requested = requested or "off"
        levels = self.thinking_levels
        if levels is None or requested in levels:
            return requested

        supported = [level for level in levels if level in THINKING_LEVELS and level != "off"]
        if not supported:
            return "off"
        if requested == "off":
            return "off" if "off" in levels else min(supported, key=THINKING_LEVELS.index)

        wanted = THINKING_LEVELS.index(requested) if requested in THINKING_LEVELS else 2
        return min(supported, key=lambda level: abs(THINKING_LEVELS.index(level) - wanted))

    def output_schema(self, schema: dict[str, Any]) -> dict[str, Any] | None:
        """返回结构化结果在该模型上使用的 schema；None 表示改用 submit_result 工具。"""
        return schema if self.structured_output else None

    def stream(self, request: ModelRequest) -> AsyncIterator[Delta]:
        raise NotImplementedError(f"{type(self).__name__} 未实现 stream()")

    async def generate(
        self,
        prompt: str | list[Message],
        *,
        system: str = "",
        thinking: str = "off",
        settings: ModelSettings | None = None,
        output: type[BaseModel] | None = None,
    ) -> Any:
        """单独调用一次模型，不写入任何会话；如需记录，请在工具中使用 ctx.generate。"""
        from work_agent_sdk.models.call import generate

        return await generate(self, prompt, system=system, thinking=thinking, settings=settings, output=output)
