from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from work_agent_sdk.core.errors import ConfigError
from work_agent_sdk.core.hooks import Hooks
from work_agent_sdk.core.model import THINKING_LEVELS, ModelCapabilities
from work_agent_sdk.core.tool import Tool, Toolset
from work_agent_sdk.core.utils import check_name


class Agent:
    def __init__(
        self,
        name: str,
        *,
        model: ModelCapabilities,
        instructions: str | Callable[..., Any] = "",
        description: str | None = None,
        thinking: str = "off",
        model_settings: Any = None,
        tools: Sequence[Tool | Toolset] = (),
        hooks: Sequence[Hooks] = (),
        output: Any = None,
        max_steps: int | None = None,
    ) -> None:
        check_name("Agent ", name)

        if not isinstance(model, ModelCapabilities):
            raise ConfigError(f"Agent {name} 的 model 须为模型对象，例如 Claude('claude-sonnet-4-5')")
        if thinking not in THINKING_LEVELS:
            raise ConfigError(f"thinking 的取值无效；可选值为 {THINKING_LEVELS}")

        for item in tools:
            if isinstance(item, str):
                raise ConfigError(f"Agent {name} 的 tools 不接受字符串 {item!r}；请传入工具或工具集对象")
            if not isinstance(item, (Tool, Toolset)):
                raise ConfigError(f"Agent {name} 的 tools 包含无法识别的对象：{item!r}；请传入工具或工具集对象")

        for hook in hooks:
            if not isinstance(hook, Hooks):
                raise ConfigError(f"Agent {name} 的 hooks 须为 Hooks 子类的实例：{hook!r}")

        if max_steps is not None and max_steps < 1:
            raise ConfigError(f"max_steps 的取值 {max_steps} 无效；须不小于 1")

        self.name = name
        self.model = model
        self.instructions = instructions
        self.description = description
        self.thinking = thinking
        self.model_settings = model_settings
        self.tools = list(tools)
        self.hooks = list(hooks)
        self.output = output
        self.max_steps = max_steps

    def __repr__(self) -> str:
        return f"Agent({self.name!r})"

    @property
    def toolsets(self) -> list[Toolset]:
        return [item for item in self.tools if isinstance(item, Toolset)]

    def related_agents(self) -> list[Agent]:
        """返回工具集中包含的其他 Agent（如 Subagents 的预设）。Runner 会一并登记，重启后按名称找回。"""
        found: list[Agent] = []
        for toolset in self.toolsets:
            for agent in getattr(toolset, "agents", ()) or ():
                if agent not in found:
                    found.append(agent)
                    found.extend(other for other in agent.related_agents() if other not in found)

        return found
