from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, TypeAdapter

ANSWERED_BY = ("user", "backend")


class Request(BaseModel):

    answered_by: ClassVar[str] = "user"

    class Answer(BaseModel):
        model_config = ConfigDict(extra="allow")

    def __init_subclass__(cls, answered_by: str | None = None, **options: Any) -> None:
        super().__init_subclass__(**options)
        if answered_by is not None:
            if answered_by not in ANSWERED_BY:
                raise ValueError(f"Invalid answered_by value; valid values are {ANSWERED_BY}")
            cls.answered_by = answered_by

    @classmethod
    def type_name(cls) -> str:
        return cls.__name__

    def answer_adapter(self) -> TypeAdapter:
        return TypeAdapter(type(self).Answer)

    def answer_schema(self) -> dict[str, Any]:
        return self.answer_adapter().json_schema()

    def sensitive(self) -> bool:
        """Whether the answer contains sensitive content, i.e. whether Answer has SecretStr or SecretBytes fields."""
        return _has_password_field(self.answer_schema())

    def parse_answer(self, value: Any) -> Any:
        return self.answer_adapter().validate_python(value)

    def data(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class Approval(Request):
    """A request asking the user for approval. Approval rules are implemented in hooks or tools."""

    title: str
    detail: Any = None

    class Answer(BaseModel):
        approved: bool
        note: str = ""


class ClientTool(Request):
    """A call to a tool with client=True: run by the frontend, which returns the result. The answer's schema is the tool's output_schema."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)

    _schema: dict[str, Any] | None = PrivateAttr(default=None)

    def __init__(self, tool: str, args: dict[str, Any] | None = None, output_schema: dict | None = None, **data: Any):
        super().__init__(tool=tool, args=args or {}, **data)
        self._schema = output_schema

    def answer_schema(self) -> dict[str, Any]:
        return dict(self._schema) if self._schema else {}

    def sensitive(self) -> bool:
        return False  # The result goes to the model, so it isn't a sensitive answer

    def parse_answer(self, value: Any) -> Any:
        return value


class Takeover(Request):
    """Ask the user to take over the browser or computer, e.g. to sign in, enter a CAPTCHA or confirm a payment."""

    reason: str
    target: str = "browser"
    node: str | None = None
    tab_id: str | None = None
    url: str | None = None

    class Answer(BaseModel):
        done: bool = True
        note: str = ""


class PendingRequest(BaseModel):
    """A request awaiting an answer, returned by session.pending()."""

    id: str
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    answer_schema: dict[str, Any] = Field(default_factory=dict)
    answered_by: str = "user"
    sensitive: bool = False  # When True, the frontend should collect the answer with something like a password field
    session_id: str
    agent: str
    call_id: str | None = None
    created_at: float = 0.0


def _has_password_field(schema: Any) -> bool:
    if isinstance(schema, dict):
        if schema.get("format") == "password":
            return True
        return any(_has_password_field(value) for value in schema.values())
    if isinstance(schema, list):
        return any(_has_password_field(item) for item in schema)
    return False
