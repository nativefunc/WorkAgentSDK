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

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: Any = None
    system: str = ""
    messages: list[Message] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    # Deferred extension tools (runner.extensions), only provided when the model uses tool_search, loaded through the API's native mechanism
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
    """Merge deltas with the same index into one call. args can be given as string chunks or as a complete dict at once."""

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
    """Base class for adapting a model provider's protocol. To integrate a custom provider, subclass this and implement stream(request)."""

    # Mapping from provider error codes to error categories, e.g. {"overloaded_error": "overloaded"}; codes not in the table are classified by HTTP status code
    error_codes: ClassVar[Mapping[str, str]] = {}
    # Whether native structured output can be used together with tools. Qwen ignores response_format when the request has tools, so such models use the submit_result tool instead
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

        # Toolsets sent in the provider's native format: "computer", "browser"
        self.native_tools = frozenset(native_tools)

        # Whether extension tools use the provider's native deferred loading (Claude's defer_loading, OpenAI Responses' tool_search);
        # pass False for older models that don't support it
        self.native_tool_search = native_tool_search

        # Images produced by the framework itself (computer screenshots, ViewImage) are scaled to within this longest edge
        self.max_image_edge = max_image_edge

        # Limit for a single image (bytes after base64). Images over the limit aren't written to the history, otherwise every later model call would be rejected
        self.max_image_bytes = max_image_bytes

        # Coordinate system (width, height) the model uses for screen coordinates. None means screenshot pixels; (1000, 1000) means relative coordinates from 0 to 1000
        self.screen_coordinates = (
            (int(screen_coordinates[0]), int(screen_coordinates[1])) if screen_coordinates else None
        )

    # Format of native toolsets: "anthropic", "openai", or None (no native format; all tools are regular tools)
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
        """Return the schema used for structured results on this model; None means use the submit_result tool instead."""
        return schema if self.structured_output else None

    def stream(self, request: ModelRequest) -> AsyncIterator[Delta]:
        raise NotImplementedError(f"{type(self).__name__} doesn't implement stream()")

    async def generate(
        self,
        prompt: str | list[Message],
        *,
        system: str = "",
        thinking: str = "off",
        settings: ModelSettings | None = None,
        output: type[BaseModel] | None = None,
    ) -> Any:
        """Call the model once on its own without writing to any session; to record it, use ctx.generate in a tool."""
        from work_agent_sdk.models.call import generate

        return await generate(
            self,
            prompt,
            system=system,
            thinking=thinking,
            settings=settings,
            output=output,
        )
