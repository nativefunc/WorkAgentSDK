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
        check_name("agent", name)

        if not isinstance(model, ModelCapabilities):
            raise ConfigError(f"The model of Agent {name} must be a model object, e.g. Claude('claude-sonnet-4-5')")
        if thinking not in THINKING_LEVELS:
            raise ConfigError(f"Invalid thinking value; valid values are {THINKING_LEVELS}")

        for item in tools:
            if isinstance(item, str):
                raise ConfigError(f"The tools of Agent {name} don't accept the string {item!r}; pass tool or toolset objects")
            if not isinstance(item, (Tool, Toolset)):
                raise ConfigError(f"The tools of Agent {name} contain an unrecognized object: {item!r}; pass tool or toolset objects")

        for hook in hooks:
            if not isinstance(hook, Hooks):
                raise ConfigError(f"The hooks of Agent {name} must be instances of Hooks subclasses: {hook!r}")

        if max_steps is not None and max_steps < 1:
            raise ConfigError(f"Invalid max_steps value {max_steps}; must be at least 1")

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
        """Return other Agents contained in the toolsets (e.g. Subagents presets). The Runner registers them too and finds them by name after a restart."""
        found: list[Agent] = []
        for toolset in self.toolsets:
            for agent in getattr(toolset, "agents", ()) or ():
                if agent not in found:
                    found.append(agent)
                    found.extend(other for other in agent.related_agents() if other not in found)

        return found
