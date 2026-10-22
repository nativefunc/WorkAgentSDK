from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter

import work_agent_sdk.strings.runtime as strings
from work_agent_sdk.core.errors import ConfigError
from work_agent_sdk.core.messages import ToolResult
from work_agent_sdk.core.tool import Tool, Toolset
from work_agent_sdk.runtime.context import jsonable
from work_agent_sdk.runtime.turn.tool_search import ToolSearch

if TYPE_CHECKING:
    from work_agent_sdk.runtime.context import RunContext
    from work_agent_sdk.runtime.worker.worker import SessionWorker

logger = logging.getLogger("work_agent_sdk")
SUBMIT_TOOL = "submit_result"
EXTENSION_WAIT = 1.0


@dataclass
class Entry:
    tool: Tool
    requires: frozenset[str]
    toolset: Toolset | None = None
    deferred: bool = False


@dataclass
class Catalog:
    entries: dict[str, Entry] = field(default_factory=dict)
    # Agent 指定了 output 时，本次请求使用的原生结构化输出 schema；None 表示改用 submit_result 工具（或未指定 output）
    output_schema: dict[str, Any] | None = None

    def direct(self) -> list[Entry]:
        return [entry for entry in self.entries.values() if not entry.deferred and not entry.tool.hidden]

    def deferred(self) -> list[Entry]:
        return [entry for entry in self.entries.values() if entry.deferred and not entry.tool.hidden]

    def get(self, name: str) -> Entry | None:
        return self.entries.get(name)

    def add(self, entry: Entry, *, strict: bool) -> None:
        name = entry.tool.name
        if name in self.entries and self.entries[name].tool is not entry.tool:
            if strict:
                raise ConfigError(f"存在两个同名工具 {name}；请为其中之一更换名称")
            logger.warning("工具集 %s 的工具 %s 与已有工具同名，已跳过", getattr(entry.toolset, "name", "?"), name)
            return
        self.entries[name] = entry


class ExtensionTools:
    # 1 秒内没返回就先用该工具集上一次的工具，不阻塞模型调用

    def __init__(self) -> None:
        self._last: dict[tuple[str, str], list[Tool]] = {}
        self._pending: dict[tuple[str, str], asyncio.Task] = {}
        self.problems: dict[tuple[str, str], str] = {}

    async def tools(self, session_id: str, toolset: Toolset, ctx: Any, *, wait: bool) -> list[Tool]:
        key = (session_id, toolset.name)
        task = self._pending.get(key)
        if task is not None and task.done() and not wait:
            # 上次未等到的获取已在后台完成：本次使用其结果，下一次调用再重新获取
            self._pending.pop(key, None)
            return self._settle(key, toolset, task)

        if task is None or task.done():
            task = self._pending[key] = asyncio.ensure_future(toolset.tools(ctx))

        try:
            if wait:
                tools = await asyncio.shield(task)
            else:
                tools = await asyncio.wait_for(asyncio.shield(task), EXTENSION_WAIT)
        except TimeoutError:
            self.problems[key] = strings.TOOL_SOURCE_PREPARING.format(name=toolset.name)
            return self._last.get(key, [])
        except Exception as error:
            self.problems[key] = f"{toolset.name}：{type(error).__name__}: {error}"
            self._pending.pop(key, None)
            return self._last.get(key, [])

        self._pending.pop(key, None)
        self.problems.pop(key, None)
        self._last[key] = list(tools)
        return list(tools)

    def _settle(self, key: tuple[str, str], toolset: Toolset, task: asyncio.Task) -> list[Tool]:
        try:
            tools = list(task.result())
        except Exception as error:
            self.problems[key] = f"{toolset.name}：{type(error).__name__}: {error}"
            return self._last.get(key, [])

        self.problems.pop(key, None)
        self._last[key] = tools
        return list(tools)

    def forget(self, session_id: str | None = None, toolset: str | None = None) -> None:
        for key in list(self._last):
            if (session_id is None or key[0] == session_id) and (toolset is None or key[1] == toolset):
                self._last.pop(key, None)
                self._pending.pop(key, None)
                self.problems.pop(key, None)


def _allowed(item: Tool | Toolset, allowed: list[str] | None) -> bool:
    return allowed is None or item.name in allowed


async def collect(worker: SessionWorker, ctx: RunContext, *, wait_extensions: bool = False) -> Catalog:
    catalog = Catalog()
    resources = set(worker.resources.names())
    task = worker.record.config.task
    allowed = task.tools if task is not None else None
    for item in worker.agent.tools:
        if not _allowed(item, allowed):
            continue
        if isinstance(item, Tool):
            if item.requires <= resources:
                catalog.add(Entry(item, item.requires), strict=True)
            continue
        if not item.requires <= resources:
            continue

        for tool in await item.tools(ctx):
            requires = tool.requires | item.requires
            if requires <= resources:
                catalog.add(Entry(tool, requires, item), strict=True)

    extensions = worker.core.extensions()
    if extensions:
        deferred = worker.model.tool_search
        cache = worker.sessions.extension_tools
        for toolset in extensions:
            if not toolset.requires <= resources:
                continue
            for tool in await cache.tools(worker.session_id, toolset, ctx, wait=wait_extensions):
                requires = tool.requires | toolset.requires
                if requires <= resources:
                    catalog.add(Entry(tool, requires, toolset, deferred=deferred), strict=False)

        if deferred:
            catalog.add(Entry(search_tool(worker), frozenset()), strict=False)

    _choose_output(worker, catalog)
    return catalog


def _choose_output(worker: SessionWorker, catalog: Catalog) -> None:
    output = worker.agent.output
    if output is None:
        return

    model = worker.model
    schema = model.output_schema(TypeAdapter(output).json_schema())
    if schema is not None and catalog.entries and not model.structured_output_with_tools:
        schema = None

    catalog.output_schema = schema
    if schema is None:
        catalog.add(Entry(submit_tool(output), frozenset()), strict=True)


def search_tool(worker: SessionWorker) -> Tool:
    async def candidates(ctx: Any) -> tuple[list[tuple[str, str, list[dict[str, Any]]]], list[str]]:
        found = await collect(worker, ctx, wait_extensions=True)
        groups: dict[str, tuple[str, str, list[dict[str, Any]]]] = {}
        for entry in found.deferred():
            toolset = entry.toolset
            name = toolset.name if toolset else "?"
            group = groups.setdefault(name, (name, (toolset.description if toolset else "") or "", []))
            group[2].append(await schema_of(entry.tool, ctx))

        cache = worker.sessions.extension_tools
        problems = [problem for key, problem in cache.problems.items() if key[0] == worker.session_id]
        return list(groups.values()), problems

    return ToolSearch(candidates)


async def schema_of(tool: Tool, ctx: Any) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "name": tool.name,
        "description": await tool.describe(ctx),
        "parameters": tool.input_schema,
    }
    if tool.native is not None:
        schema["toolset"] = list(tool.native)
    return schema


def submit_tool(output_type: Any) -> Tool:
    adapter = TypeAdapter(output_type)
    schema = adapter.json_schema()
    wrapped = schema.get("type") != "object"
    parameters = {"type": "object", "properties": {"result": schema}, "required": ["result"]} if wrapped else schema

    class SubmitResult(Tool):
        async def run(self, ctx: Any, args: dict[str, Any]) -> Any:
            value = adapter.validate_python(args["result"] if wrapped else args)
            ctx.end_turn()
            return ToolResult(text=strings.SUBMITTED, data=jsonable(value))

        def validate_args(self, args: dict[str, Any]) -> dict[str, Any]:
            return dict(args)

    return SubmitResult(name=SUBMIT_TOOL, description=strings.SUBMIT_DESCRIPTION, input_schema=parameters)
