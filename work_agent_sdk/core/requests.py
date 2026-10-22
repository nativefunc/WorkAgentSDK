from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, TypeAdapter

ANSWERED_BY = ("user", "backend")


class Request(BaseModel):
    """需要外部答复的请求。字段为展示给前端的内容，内部类 Answer 为答复的类型。"""

    answered_by: ClassVar[str] = "user"

    class Answer(BaseModel):
        model_config = ConfigDict(extra="allow")

    def __init_subclass__(cls, answered_by: str | None = None, **options: Any) -> None:
        super().__init_subclass__(**options)
        if answered_by is not None:
            if answered_by not in ANSWERED_BY:
                raise ValueError(f"answered_by 的取值无效；可选值为 {ANSWERED_BY}")
            cls.answered_by = answered_by

    @classmethod
    def type_name(cls) -> str:
        return cls.__name__

    def answer_adapter(self) -> TypeAdapter:
        return TypeAdapter(type(self).Answer)

    def answer_schema(self) -> dict[str, Any]:
        return self.answer_adapter().json_schema()

    def sensitive(self) -> bool:
        """答复是否包含敏感内容，即 Answer 中是否有 SecretStr 或 SecretBytes 字段。"""
        return _has_password_field(self.answer_schema())

    def parse_answer(self, value: Any) -> Any:
        return self.answer_adapter().validate_python(value)

    def data(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class Approval(Request):
    """审批请求。框架只提供类型，审批规则由开发者在钩子或工具中实现。"""

    title: str
    detail: Any = None

    class Answer(BaseModel):
        approved: bool
        note: str = ""


class ClientTool(Request):
    """client=True 的工具调用：由前端执行并返回结果。答复的 schema 为工具的 output_schema。"""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)

    _schema: dict[str, Any] | None = PrivateAttr(default=None)

    def __init__(self, tool: str, args: dict[str, Any] | None = None, output_schema: dict | None = None, **data: Any):
        super().__init__(tool=tool, args=args or {}, **data)
        self._schema = output_schema

    def answer_schema(self) -> dict[str, Any]:
        return dict(self._schema) if self._schema else {}

    def sensitive(self) -> bool:
        return False  # 结果将交给模型，不属于敏感答复

    def parse_answer(self, value: Any) -> Any:
        return value


class Takeover(Request):
    """请求用户接管浏览器或电脑，例如登录、输入验证码或确认付款。"""

    reason: str
    target: str = "browser"
    node: str | None = None
    tab_id: str | None = None
    url: str | None = None

    class Answer(BaseModel):
        done: bool = True
        note: str = ""


class PendingRequest(BaseModel):
    """等待答复的请求，由 session.pending() 返回。"""

    id: str
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    answer_schema: dict[str, Any] = Field(default_factory=dict)
    answered_by: str = "user"
    sensitive: bool = False  # 为 True 时前端应以密码输入框等方式收集答复
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
