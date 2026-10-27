from __future__ import annotations

import base64
import time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, model_validator

from work_agent_sdk.core.utils import new_id

MessageStatus = Literal["in_progress", "waiting", "completed", "failed", "cancelled", "interrupted"]
FINISHED: frozenset[str] = frozenset({"completed", "failed", "cancelled", "interrupted"})

IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def image_mime_type(data: bytes) -> str | None:
    for signature, mime_type in IMAGE_SIGNATURES:
        if data.startswith(signature):
            return mime_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str
    signature: str | None = None


class MediaPart(BaseModel):
    """Image, audio or video. data is base64-encoded"""

    type: Literal["media"] = "media"
    kind: str = "image"
    mime: str = "image/png"
    data: str
    path: str | None = None

    @classmethod
    def image(cls, **fields: Any) -> MediaPart:
        return cls(kind="image", **fields)

    @classmethod
    def image_bytes(cls, data: bytes, *, path: str | None = None) -> MediaPart:
        mime = image_mime_type(data)
        if mime is None:
            raise ValueError("Only png, jpeg, gif and webp images are supported")
        return cls(kind="image", mime=mime, data=base64.b64encode(data).decode(), path=path)


class ThinkingPart(BaseModel):

    type: Literal["thinking"] = "thinking"
    text: str = ""
    signature: str | None = None
    redacted: bool = False # Whether the thinking is encrypted


Part = Annotated[TextPart | MediaPart | ThinkingPart, Field(discriminator="type")]


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )


class ToolCall(BaseModel):
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    signature: str | None = None
    # Why the arguments couldn't be parsed: truncated (output hit the length limit) or invalid (not a JSON object)
    args_error: str | None = None


class _AcceptsText(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _accept_text(cls, values: Any) -> Any:
        if not isinstance(values, dict) or "text" not in values:
            return values

        values = dict(values)
        text = values.pop("text")
        if text is not None:
            values["content"] = [TextPart(text=text), *values.get("content", [])]

        return values


def _text_of(content: list[Any]) -> str:
    return "".join(part.text for part in content if isinstance(part, TextPart))


class ToolResult(_AcceptsText):
    """The result of running a tool. content is given to the model; data is given to the frontend and the program."""

    content: list[Part] = Field(default_factory=list)
    data: Any = None
    error: str | None = None
    error_code: str | None = None
    loaded_tools: list[str] = Field(default_factory=list)

    @property
    def text(self) -> str:
        return _text_of(self.content)

    @property
    def is_error(self) -> bool:
        return self.error is not None


class BaseMessage(BaseModel):
    id: str = Field(default_factory=lambda: new_id("msg_"))
    status: MessageStatus = "completed"
    created_at: float = Field(default_factory=time.time)
    completed_at: float | None = None
    turn_id: str | None = None

    @property
    def text(self) -> str:
        return _text_of(getattr(self, "content", []))

    @property
    def media(self) -> list[MediaPart]:
        return [part for part in getattr(self, "content", []) if isinstance(part, MediaPart)]

    @property
    def finished(self) -> bool:
        return self.status in FINISHED


class UserMessage(_AcceptsText, BaseMessage):
    role: Literal["user"] = "user"
    content: list[Part] = Field(default_factory=list)


class AssistantMessage(_AcceptsText, BaseMessage):
    """One response from the model. stop_reason is stop, tool_use, length, stopped or error."""

    role: Literal["assistant"] = "assistant"
    content: list[Part] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    model: str | None = None
    usage: Usage | None = None
    stop_reason: str | None = None
    thinking_duration: float | None = None
    data: Any = None
    error: str | None = None
    error_code: str | None = None

    @property
    def thinking_text(self) -> str:
        parts = [part for part in self.content if isinstance(part, ThinkingPart)]
        return "".join(part.text for part in parts if not part.redacted)


class ToolResultMessage(_AcceptsText, BaseMessage):
    """How one tool call ran and its result."""

    role: Literal["tool"] = "tool"
    tool_call_id: str
    tool_name: str
    content: list[Part] = Field(default_factory=list)
    data: Any = None
    error: str | None = None
    error_code: str | None = None
    open_world: bool = False
    loaded_tools: list[str] = Field(default_factory=list)


class CustomMessage(BaseMessage):

    role: Literal["custom"] = "custom"
    kind: str
    data: Any = None
    display: bool = True
    for_model: str | None = None

    def __init__(self, kind: str | None = None, data: Any = None, **fields: Any) -> None:
        if kind is not None:
            fields["kind"] = kind
        if data is not None:
            fields["data"] = data
        super().__init__(**fields)

    @property
    def text(self) -> str:
        return self.for_model or ""


Message = Annotated[
    UserMessage | AssistantMessage | ToolResultMessage | CustomMessage,
    Field(discriminator="role"),
]
MESSAGE_ADAPTER: TypeAdapter[Message] = TypeAdapter(Message)


def parse_message(data: Any) -> Message:
    if isinstance(data, BaseMessage):
        return data
    return MESSAGE_ADAPTER.validate_python(data)
