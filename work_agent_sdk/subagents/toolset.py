from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Annotated, Any

from pydantic import Field

import work_agent_sdk.strings.subagents as strings
from work_agent_sdk.core.agent import Agent
from work_agent_sdk.core.errors import ConfigError, ToolError
from work_agent_sdk.core.tool import Context, Tool, Toolset


class Subagents(Toolset):
    name = "subagents"
    description = "委派子智能体执行任务"

    def __init__(
        self,
        foreground: Sequence[Agent] = (),
        background: Sequence[Agent] = (),
        *,
        dynamic: Agent | None = None,
        max_background: int = 4,
        agent_description: str | None = None,
    ) -> None:
        """agent_description 替换 agent 工具的说明；可委派的子智能体列表在其 type 参数的说明中，不受影响。"""
        super().__init__()
        self.agent_description = agent_description
        self.foreground = list(foreground)
        self.background = list(background)
        self.dynamic = dynamic
        self.max_background = max_background
        presets = self.foreground + self.background
        self.agents = [*presets, *([dynamic] if dynamic else [])]
        if not self.agents:
            raise ConfigError("Subagents 未配置任何子智能体；请传入 foreground、background 或 dynamic")
        if max_background < 1:
            raise ConfigError(f"max_background 的取值 {max_background} 无效；须不小于 1")

        # 按需创建的子智能体也按名字选择，因此与预设子智能体一起不得重名
        names = [agent.name for agent in self.agents]
        if len(set(names)) != len(names):
            raise ConfigError("子智能体名称重复（包括 dynamic 模板）；请为每个子智能体指定不同的名称")

        for agent in presets:
            if not agent.description:
                raise ConfigError(f"子智能体 {agent.name} 缺少 description；上级依据该说明选择要委派的子智能体")

        for agent in self.agents:
            if any(isinstance(item, Subagents) for item in agent.tools):
                raise ConfigError(f"子智能体 {agent.name} 不能再包含 Subagents；子会话不支持继续委派")

    def __repr__(self) -> str:
        return f"Subagents({[agent.name for agent in self.agents]})"

    @property
    def has_background(self) -> bool:
        return bool(self.background) or self.dynamic is not None

    async def tools(self, ctx: Context) -> list[Tool]:
        if ctx.parent_id is not None:
            return []  # 子会话不能继续委派

        tools = [self._agent_tool()]
        if self.has_background:
            tools += [
                Tool(self._message_agent, name="message_agent", description=strings.MESSAGE_AGENT_DESCRIPTION),
                Tool(self._close_agent, name="close_agent", description=strings.CLOSE_AGENT_DESCRIPTION),
                Tool(
                    self._list_agents,
                    name="list_agents",
                    description=strings.LIST_AGENTS_DESCRIPTION,
                    annotations={"read_only": True},
                ),
            ]

        return tools

    async def _describe(self, ctx: Context) -> str:
        if self.agent_description is not None:
            return self.agent_description

        lines = [strings.AGENT_INTRO]
        if self.foreground or self.dynamic is not None:
            lines.append(strings.AGENT_FOREGROUND_MODE)
        if self.has_background:
            lines.append(strings.AGENT_BACKGROUND_MODE)
        if ctx.has_resource("workspace"):
            lines.append(strings.AGENT_SHARED_WORKSPACE)

        return "\n".join(lines)

    def _agent_tool(self) -> Tool:
        lines = [strings.AGENT_FOREGROUND.format(name=a.name, description=a.description) for a in self.foreground]
        lines += [strings.AGENT_BACKGROUND.format(name=a.name, description=a.description) for a in self.background]
        types = [agent.name for agent in self.foreground + self.background]
        properties: dict[str, Any] = {
            "type": {"type": "string", "enum": types},
            "prompt": {"type": "string", "description": strings.AGENT_PROMPT},
        }
        if self.dynamic is not None:
            dynamic = self.dynamic.name
            types.append(dynamic)
            choices = [item.name for item in self.dynamic.tools]
            lines.append(
                strings.AGENT_DYNAMIC.format(
                    name=dynamic,
                    description=f"{self.dynamic.description}。" if self.dynamic.description else "",
                    tools="、".join(choices) or strings.AGENT_NO_TOOLS,
                )
            )
            properties["background"] = {
                "type": "boolean",
                "description": strings.AGENT_DYNAMIC_BACKGROUND.format(name=dynamic),
            }
            properties["tools"] = {
                "type": "array",
                "items": {"type": "string", "enum": choices},
                "description": strings.AGENT_DYNAMIC_TOOLS.format(name=dynamic),
            }

        properties["type"]["description"] = strings.AGENT_TYPE.format(agents="\n".join(lines))
        dispatch = self._dispatch

        class AgentTool(Tool):
            async def run(self, ctx: Any, args: dict[str, Any]) -> Any:
                return await dispatch(ctx, args)

        return AgentTool(
            name="agent",
            description=self._describe,
            input_schema={"type": "object", "properties": properties, "required": ["type", "prompt"]},
            parallel=True,
        )

    def _choose(self, args: dict[str, Any]) -> tuple[Agent, bool, list[str] | None]:
        kind = args.get("type")
        if self.dynamic is not None and kind == self.dynamic.name:
            tools = args.get("tools")
            if tools is not None:
                choices = {item.name for item in self.dynamic.tools}
                unknown = [name for name in tools if name not in choices]
                if unknown:
                    raise ToolError(f"以下工具不可提供：{'、'.join(unknown)}", code="invalid_arguments")
            return self.dynamic, bool(args.get("background")), tools

        preset = next((item for item in self.foreground + self.background if item.name == kind), None)
        if preset is None:
            raise ToolError(f"子智能体 {kind} 不存在", code="invalid_arguments")
        return preset, preset in self.background, None

    async def _dispatch(self, ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            raise ToolError("prompt 不能为空", code="invalid_arguments")

        agent, background, tools = self._choose(args)
        tasks = ctx.tasks
        if background:
            running = [
                info
                for info in await tasks.list()
                if info.status == "open" and info.task and info.task.mode == "background"
            ]
            if len(running) >= self.max_background:
                raise ToolError(
                    f"后台子智能体已达上限（{self.max_background} 个）；请先关闭不再需要的后台子智能体",
                    code="too_many",
                )

        task_id = await tasks.spawn(agent.name, background=background, tools=tools)
        if background:
            await tasks.send(task_id, prompt)
            return {"agent": agent.name, "id": task_id, "status": "running"}

        result = await tasks.wait(task_id, prompt)
        report = result.for_model()
        if result.status != "completed":
            raise ToolError(json.dumps(report, ensure_ascii=False), code="subagent_failed", data=report)
        return report

    async def _own_background(self, ctx: Context, agent_id: str) -> Any:
        info = await ctx.tasks.get(agent_id)
        if info is None or info.task is None or info.task.mode != "background":
            raise ToolError(f"后台子智能体 {agent_id} 不存在", code="not_found")
        return info

    async def _message_agent(
        self,
        ctx: Context,
        agent_id: Annotated[str, Field(description=strings.AGENT_ID)],
        message: Annotated[str, Field(description=strings.AGENT_MESSAGE)],
    ) -> str:
        info = await self._own_background(ctx, agent_id)
        if info.status != "open":
            raise ToolError(strings.AGENT_ALREADY_CLOSED.format(name=info.agent, id=agent_id), code="closed")

        await ctx.tasks.send(agent_id, message)
        return strings.MESSAGE_SENT.format(name=info.agent, id=agent_id)

    async def _close_agent(self, ctx: Context, agent_id: Annotated[str, Field(description=strings.AGENT_ID)]) -> str:
        info = await self._own_background(ctx, agent_id)
        if info.status != "open":
            return strings.AGENT_ALREADY_CLOSED.format(name=info.agent, id=agent_id)

        await ctx.step(f"close:{agent_id}", lambda: ctx.tasks.close(agent_id))
        return strings.AGENT_CLOSED.format(name=info.agent, id=agent_id)

    async def _list_agents(self, ctx: Context) -> dict[str, Any]:
        available = [
            {"name": agent.name, "description": agent.description, "background": agent in self.background}
            for agent in self.foreground + self.background
        ]
        running = [
            {"id": info.id, "agent": info.agent, "status": info.status, "activity": info.activity}
            for info in await ctx.tasks.list()
            if info.task is not None and info.task.mode == "background"
        ]
        return {"available": available, "background": running}


__all__ = ["Subagents"]
