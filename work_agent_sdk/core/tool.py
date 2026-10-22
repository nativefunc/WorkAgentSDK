from __future__ import annotations

import asyncio
import copy
import inspect
import json
from collections.abc import Callable, Sequence
from typing import (
    TYPE_CHECKING,
    Any,
    Protocol,
    TypeVar,
    get_type_hints,
    runtime_checkable,
)

from pydantic import BaseModel, ConfigDict, TypeAdapter, create_model

from work_agent_sdk.core.errors import ConfigError, ToolError
from work_agent_sdk.core.messages import (
    CustomMessage,
    MediaPart,
    TextPart,
    ToolCall,
    ToolResult,
)
from work_agent_sdk.core.model import ModelCapabilities
from work_agent_sdk.core.requests import ClientTool, Request
from work_agent_sdk.core.utils import check_name, matches_any, maybe_await

if TYPE_CHECKING:
    from work_agent_sdk.core.agent import Agent
    from work_agent_sdk.core.hooks import Hooks
    from work_agent_sdk.core.results import SessionInfo, TaskResult
    from work_agent_sdk.core.service import Service

S = TypeVar("S")
ANNOTATIONS = ("read_only", "destructive", "open_world", "interactive")


@runtime_checkable
class TaskControl(Protocol):
    """子会话操作接口，仅可在工具调用中使用。"""

    async def spawn(self, agent: Agent | str, *, background: bool = False, tools: list[str] | None = None) -> str: ...
    async def wait(self, task_id: str, prompt: str) -> TaskResult: ...
    async def send(self, task_id: str, prompt: str) -> None: ...
    async def close(self, task_id: str) -> None: ...
    async def get(self, task_id: str) -> SessionInfo | None: ...
    async def list(self) -> list[SessionInfo]: ...


@runtime_checkable
class Context(Protocol):
    """工具和钩子获得的上下文。"""

    @property
    def session_id(self) -> str: ...
    @property
    def root_id(self) -> str: ...
    @property
    def parent_id(self) -> str | None: ...
    @property
    def agent(self) -> str: ...
    @property
    def turn_id(self) -> str | None: ...
    @property
    def session(self) -> Any: ...

    turn: Any
    call: ToolCall | None
    tool: Tool | None

    @property
    def model(self) -> ModelCapabilities: ...
    @property
    def workspace(self) -> Any: ...
    @property
    def computer(self) -> Any: ...
    @property
    def browser(self) -> Any: ...
    @property
    def tasks(self) -> TaskControl: ...

    async def resource(self, name: str, *, wait: bool = True) -> Any: ...
    def has_resource(self, name: str) -> bool: ...
    def service(self, kind: type[S]) -> S: ...
    def step_key(self, name: str) -> str: ...
    async def step(self, name: str, fn: Callable[[], Any]) -> Any: ...
    async def wait_for(self, request: Request) -> Any: ...
    async def stream(self, data: Any) -> None: ...
    async def add_message(self, message: CustomMessage) -> CustomMessage: ...
    async def update_message(self, message_id: str, **changes: Any) -> None: ...
    async def complete_message(self, message_id: str, **changes: Any) -> None: ...
    def end_turn(self) -> None: ...
    async def generate(
        self,
        prompt: Any,
        *,
        system: str = "",
        thinking: str = "off",
        settings: Any = None,
        output: Any = None,
        model: Any = None,
    ) -> Any: ...


def to_result(value: Any) -> ToolResult:
    if isinstance(value, ToolResult):
        return value
    if value is None:
        return ToolResult(text="已完成")
    if isinstance(value, str):
        return ToolResult(text=value)
    if isinstance(value, (TextPart, MediaPart)):
        return ToolResult(content=[value])
    if isinstance(value, BaseModel):
        return _json_result(value.model_dump(mode="json"))
    if isinstance(value, list) and value and all(isinstance(item, (TextPart, MediaPart)) for item in value):
        return ToolResult(content=list(value))
    if isinstance(value, list) and value and all(isinstance(item, BaseModel) for item in value):
        return _json_result([item.model_dump(mode="json") for item in value])

    try:
        data = json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return ToolResult(text=str(value))

    return _json_result(data)


def _json_result(data: Any) -> ToolResult:
    return ToolResult(content=[TextPart(text=json.dumps(data, ensure_ascii=False))], data=data)


def without_titles(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {key: without_titles(value) for key, value in schema.items() if key != "title"}
    if isinstance(schema, list):
        return [without_titles(value) for value in schema]
    return schema


def resolve_hints(function: Callable, tool_name: str) -> dict[str, Any]:
    target = getattr(function, "__func__", function)
    namespace: dict[str, Any] = {"Context": Context, **getattr(target, "__globals__", {})}
    closure = getattr(target, "__closure__", None) or ()
    for name, cell in zip(target.__code__.co_freevars, closure, strict=True):
        try:
            namespace[name] = cell.cell_contents
        except ValueError:
            continue

    try:
        return get_type_hints(target, globalns=namespace, include_extras=True)
    except Exception as error:
        raise ConfigError(f"无法解析工具 {tool_name} 的参数类型：{error}") from error


def _is_context_parameter(parameter: inspect.Parameter, hints: dict[str, Any]) -> bool:
    annotation = hints.get(parameter.name)
    if annotation is None:
        return parameter.name in ("ctx", "context")
    return annotation is Context


class Tool:
    """可由模型调用的函数。通常通过 @tool 创建；如需自行控制 schema，请继承此类并实现 run(ctx, args)。"""

    name: str = ""
    description: str | Callable[..., Any] | None = None
    requires: frozenset[str] = frozenset()

    def __init__(
        self,
        function: Callable | None = None,
        *,
        name: str | None = None,
        description: str | Callable[..., Any] | None = None,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        parallel: bool = False,
        annotations: dict[str, Any] | None = None,
        timeout: float | None = None,
        end_turn: bool = False,
        client: bool = False,
        requires: Sequence[str] = (),
        native: tuple[str, str] | None = None,
    ) -> None:
        self.function = function
        self.name = check_name("工具", name or self.name or (function.__name__ if function else ""))
        self.description = description if description is not None else self.description
        if not self.description:
            raise ConfigError(f"工具 {self.name} 缺少 description；description 是模型了解该工具的唯一依据")

        self.parallel = parallel
        self.annotations: dict[str, Any] = dict(annotations or {})
        unknown = set(self.annotations) - set(ANNOTATIONS)
        if unknown:
            raise ConfigError(f"工具 {self.name} 的 annotations 包含未知项 {sorted(unknown)}；可用项为 {ANNOTATIONS}")
        if client:
            self.annotations.setdefault("interactive", True)

        self.timeout = timeout
        self.end_turn = end_turn
        self.client = client
        self.requires = frozenset(requires) | frozenset(type(self).requires)
        self.native = native

        # 不发送给模型，但仍可执行（切换模型后，记录中另一种形式的调用仍需能够执行）
        self.hidden = False
        self.instance: Any = None
        self._input_schema = input_schema
        self._output_schema = output_schema
        self._arguments_model: type[BaseModel] | None = None
        self._takes_context = False
        self._return_type: Any = None
        if function is not None:
            self._inspect_function(function)

    def __repr__(self) -> str:
        return f"Tool({self.name!r})"

    @property
    def input_schema(self) -> dict[str, Any]:
        if self._input_schema is not None:
            return self._input_schema
        if self._arguments_model is None:
            return {"type": "object", "properties": {}}
        return without_titles(self._arguments_model.model_json_schema())

    @property
    def output_schema(self) -> dict[str, Any] | None:
        if self._output_schema is not None:
            return self._output_schema
        if self._return_type is None:
            return None
        try:
            return without_titles(TypeAdapter(self._return_type).json_schema())
        except Exception:
            return None

    @property
    def open_world(self) -> bool:
        return bool(self.annotations.get("open_world"))

    @property
    def read_only(self) -> bool:
        return bool(self.annotations.get("read_only"))

    async def describe(self, ctx: Context) -> str:
        description = self.description
        if callable(description):
            description = await maybe_await(description(ctx))
        return str(description)

    def copy(self, **changes: Any) -> Tool:
        copied = copy.copy(self)
        for key, value in changes.items():
            setattr(copied, key, value)
        return copied

    def bind(self, instance: Any) -> Tool:
        return self.copy(instance=instance)

    def validate_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """校验参数，不合格时抛出 pydantic.ValidationError 或 jsonschema.ValidationError。"""
        if self._arguments_model is not None:
            parsed = self._arguments_model.model_validate(args)
            return {name: getattr(parsed, name) for name in type(parsed).model_fields}

        if self._input_schema:
            import jsonschema

            jsonschema.validate(args, self._input_schema)

        return dict(args)

    async def invoke(self, ctx: Context, args: dict[str, Any]) -> ToolResult:
        """执行工具并转换为 ToolResult；定义了 output_schema 时校验 data。"""
        if self.timeout is None:
            value = await self.run(ctx, args)
        else:
            try:
                value = await asyncio.wait_for(self.run(ctx, args), timeout=self.timeout)
            except TimeoutError:
                raise ToolError(f"工具 {self.name} 执行超过 {self.timeout:g} 秒，已取消", code="timeout") from None

        result = to_result(value)
        schema = self.output_schema
        if schema and result.data is not None and not result.is_error:
            import jsonschema

            try:
                jsonschema.validate(result.data, schema)
            except jsonschema.ValidationError as error:
                raise ToolError(
                    f"工具 {self.name} 的返回值不符合 output_schema：{error.message}", code="invalid_output"
                ) from None

        return result

    async def run(self, ctx: Context, args: dict[str, Any]) -> Any:
        if self.client:
            return await self._run_on_client(ctx, args)
        if self.function is None:
            raise NotImplementedError(f"工具 {self.name} 未实现 run()")

        positional: list[Any] = []
        if self.instance is not None:
            positional.append(self.instance)
        if self._takes_context:
            positional.append(ctx)

        keywords = self.validate_args(args)
        if inspect.iscoroutinefunction(self.function):
            return await self.function(*positional, **keywords)
        return await asyncio.to_thread(self.function, *positional, **keywords)

    async def _run_on_client(self, ctx: Context, args: dict[str, Any]) -> Any:
        if self._arguments_model is not None:
            args = self._arguments_model.model_validate(args).model_dump(mode="json")
        return await ctx.wait_for(ClientTool(self.name, args, self.output_schema))

    def _inspect_function(self, function: Callable) -> None:
        signature = inspect.signature(function)
        hints = resolve_hints(function, self.name)
        parameters = list(signature.parameters.values())
        if parameters and parameters[0].name == "self":
            parameters = parameters[1:]

        fields: dict[str, Any] = {}
        for position, parameter in enumerate(parameters):
            if _is_context_parameter(parameter, hints):
                if position != 0:
                    raise ConfigError(f"工具 {self.name} 的 Context 参数须为第一个参数")
                self._takes_context = True
                continue
            if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
                continue

            annotation = hints.get(parameter.name, Any)
            default = ... if parameter.default is inspect.Parameter.empty else parameter.default
            fields[parameter.name] = (annotation, default)

        if self._input_schema is None:
            self._arguments_model = create_model(f"{self.name}_args", __config__=ConfigDict(extra="ignore"), **fields)

        return_type = hints.get("return", inspect.Signature.empty)
        # 返回 ToolResult 时 data 的结构由开发者决定，不能用 ToolResult 自身的结构校验
        returns_result = isinstance(return_type, type) and issubclass(return_type, ToolResult)
        if return_type not in (inspect.Signature.empty, None, type(None), Any) and not returns_result:
            self._return_type = return_type


def tool(
    function: Callable | None = None,
    *,
    description: str | Callable[..., Any],
    name: str | None = None,
    parallel: bool = False,
    annotations: dict[str, Any] | None = None,
    timeout: float | None = None,
    end_turn: bool = False,
    client: bool = False,
    requires: Sequence[str] = (),
    output_schema: dict[str, Any] | None = None,
) -> Any:
    """将函数转换为工具。description 为必填项，是模型了解该工具的唯一依据。"""

    def decorate(target: Callable) -> Tool:
        return Tool(
            target,
            name=name,
            description=description,
            parallel=parallel,
            annotations=annotations,
            timeout=timeout,
            end_turn=end_turn,
            client=client,
            requires=requires,
            output_schema=output_schema,
        )

    if function is not None:
        return decorate(function)
    return decorate


class Toolset:
    """一组工具。按会话提供不同的工具时，继承此类并实现 tools(ctx)。"""

    name: str = "toolset"
    description: str | None = None
    needs: tuple[type[Service], ...] = ()
    requires: frozenset[str] = frozenset()

    def __init__(
        self,
        name: str | None = None,
        *,
        tools: Sequence[Tool] = (),
        description: str | None = None,
        requires: Sequence[str] = (),
        hooks: Sequence[Hooks] = (),
    ) -> None:
        if name is not None:
            self.name = name

        check_name("工具集", self.name)

        if description is not None:
            self.description = description

        self.requires = frozenset(requires) | frozenset(type(self).requires)
        self._given_tools = list(tools)
        for item in self._given_tools:
            if not isinstance(item, Tool):
                raise ConfigError(f"工具集 {self.name} 的 tools 包含非工具对象：{item!r}")

        self.hooks: list[Hooks] = list(hooks)
        self.agents: list[Agent] = list(getattr(self, "agents", []) or [])

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r})"

    async def tools(self, ctx: Context) -> list[Tool]:
        return list(getattr(self, "_given_tools", []))

    def only(self, *patterns: str) -> Toolset:
        return Filtered(self, include=patterns)

    def exclude(self, *patterns: str) -> Toolset:
        return Filtered(self, exclude=patterns)


class Filtered(Toolset):
    def __init__(self, inner: Toolset, *, include: tuple[str, ...] = (), exclude: tuple[str, ...] = ()) -> None:
        self.inner = inner
        self.name = inner.name
        self.description = inner.description
        self.needs = inner.needs
        self.requires = inner.requires
        self.hooks = inner.hooks
        self.agents = inner.agents
        self.include = include
        self.exclude_patterns = exclude

    def __repr__(self) -> str:
        return repr(self.inner)

    async def tools(self, ctx: Context) -> list[Tool]:
        selected = []
        for item in await self.inner.tools(ctx):
            if self.include and not matches_any(item.name, self.include):
                continue
            if self.exclude_patterns and matches_any(item.name, self.exclude_patterns):
                continue
            selected.append(item)
        return selected

    def __getattr__(self, attribute: str) -> Any:
        return getattr(self.inner, attribute)


def unwrap(toolset: Toolset) -> Toolset:
    while isinstance(toolset, Filtered):
        toolset = toolset.inner
    return toolset
