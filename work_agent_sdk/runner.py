from __future__ import annotations

import contextlib
import logging
import os
import time
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from work_agent_sdk.core.agent import Agent
from work_agent_sdk.core.errors import ConfigError
from work_agent_sdk.core.events import Event, EventBus
from work_agent_sdk.core.hooks import Hooks
from work_agent_sdk.core.model import THINKING_LEVELS
from work_agent_sdk.core.results import SessionConfig
from work_agent_sdk.core.secrets import KeyProvider, key_provider
from work_agent_sdk.core.service import Service
from work_agent_sdk.core.tool import Toolset, unwrap
from work_agent_sdk.nodes.base import Node
from work_agent_sdk.nodes.local import Local
from work_agent_sdk.nodes.registry import NodeProvider, NodeRegistry, Nodes
from work_agent_sdk.nodes.shared import SharedFolder
from work_agent_sdk.nodes.tokens import DeviceTokens, SqliteDeviceTokens
from work_agent_sdk.runtime.session import Session
from work_agent_sdk.runtime.sessions import Sessions
from work_agent_sdk.store import LocalStore, Store

logger = logging.getLogger("work_agent_sdk")


def _builtin_services() -> list[Service]:
    from work_agent_sdk.browser.service import BrowserService
    from work_agent_sdk.computer.service import ComputerService
    from work_agent_sdk.workspace.service import WorkspaceService

    return [WorkspaceService(), ComputerService(), BrowserService()]


class _Core:
    def __init__(
        self,
        *,
        data_dir: Path,
        store: Store,
        secret_key: KeyProvider | None,
        hooks: list[Hooks],
        tokens: DeviceTokens,
    ) -> None:
        self.data_dir = data_dir
        self.store = store
        self.secret_key = secret_key
        self.hooks = hooks
        self.bus = EventBus()
        self.nodes = NodeRegistry(tokens, self.bus.publish)
        self.started_at = time.time()
        self.started = False
        self.agents: dict[str, Agent] = {}
        self.models: dict[str, Any] = {}
        self.service_list: list[Service] = []
        self.toolsets: dict[str, Toolset] = {}

    def agent(self, name: str) -> Agent:
        agent = self.agents.get(name)
        if agent is None:
            raise ConfigError(f"Agent {name!r} is not registered with the Runner; register it with Runner(agents=[...])")
        return agent

    def model(self, model_id: str) -> Any:
        model = self.models.get(model_id)
        if model is None:
            raise ConfigError(f"Model {model_id!r} is not registered; register it with Runner(models=[...])")
        return model

    def provider(self, resource: str) -> Service | None:
        return next((service for service in self.service_list if service.provides == resource), None)

    def services(self) -> list[Service]:
        return list(self.service_list)

    def service(self, kind: type) -> Any:
        for service in self.service_list:
            if isinstance(service, kind):
                return service
        raise ConfigError(f"Service {kind.__name__} is not registered with the Runner; register it with Runner(services=[...])")

    def extensions(self) -> list[Toolset]:
        return list(self.toolsets.values())

    def publish(self, event: Event) -> None:
        self.bus.publish(event)

    def add_service(self, service: Service) -> None:
        if not isinstance(service, Service):
            raise ConfigError(f"services must be instances of Service subclasses: {service!r}")
        if self.started:
            raise ConfigError("Services can't be added after the Runner has started; register them before starting")
        if any(type(item) is type(service) for item in self.service_list):
            raise ConfigError(f"Service {type(service).__name__} registered more than once; each kind of service can only have one instance")
        if service.provides and any(item.provides == service.provides for item in self.service_list):
            raise ConfigError(f"Resource {service.provides!r} already has a provider; each resource can only be provided by one service")

        self.service_list.append(service)

    def require_services(self, toolset: Toolset) -> None:
        for kind in unwrap(toolset).needs:
            if any(type(existing) is kind for existing in self.service_list):
                continue
            if self.started:
                raise ConfigError(f"Service {kind.__name__} required by toolset {toolset.name} is not registered; register it before the Runner starts")
            self.add_service(kind())

    def add_agent(self, agent: Agent) -> None:
        if not isinstance(agent, Agent):
            raise ConfigError(f"agents must be Agent instances: {agent!r}")

        existing = self.agents.get(agent.name)
        if existing is not None:
            if existing is not agent:
                raise ConfigError(f"Two different Agents are both named {agent.name}; give them different names")
            return

        self.agents[agent.name] = agent
        for toolset in agent.toolsets:
            self.require_services(toolset)
        for related in agent.related_agents():
            self.add_agent(related)


class Extensions:
    def __init__(self, core: _Core, runtime: Sessions) -> None:
        self._core = core
        self._runtime = runtime
        self._items = core.toolsets

    def __len__(self) -> int:
        return len(self._items)

    def add(self, toolset: Toolset) -> None:
        if not isinstance(toolset, Toolset):
            raise ConfigError(f"extensions only accepts Toolset instances: {toolset!r}")
        if toolset.hooks:
            raise ConfigError(f"Toolsets in extensions can't contain hooks: {toolset.name}; register hooks with Runner(hooks=[...])")
        if toolset.name in self._items:
            raise ConfigError(f"A toolset named {toolset.name} is already installed")

        self._core.require_services(toolset)
        self._items[toolset.name] = toolset

        if self._core.started:
            runtime = self._runtime
            runtime.api.run_in_background(runtime.lifecycle.notify("toolset_added", toolset))

    async def remove(self, name: str) -> None:
        toolset = self._items.pop(name, None)
        if toolset is None:
            return

        self._runtime.extension_tools.forget(toolset=name)
        await self._runtime.lifecycle.notify("toolset_removed", toolset)

    def list(self) -> list[Toolset]:
        return list(self._items.values())

    def get(self, name: str) -> Toolset | None:
        return self._items.get(name)


class Runner:
    def __init__(
        self,
        *,
        agents: Sequence[Agent] = (),
        data_dir: str = "~/.work-agent/runner",
        store: Store | None = None,
        nodes: Sequence[Node] | None = None,
        node_providers: dict[str, NodeProvider] | None = None,
        shared_folders: Sequence[SharedFolder] = (),
        extensions: Sequence[Toolset] = (),
        services: Sequence[Service] = (),
        models: Sequence[Any] = (),
        hooks: Sequence[Hooks] = (),
        secret_key: str | KeyProvider | None = None,
        device_tokens: DeviceTokens | None = None,
    ) -> None:
        for hook in hooks:
            if not isinstance(hook, Hooks):
                raise ConfigError(f"hooks must be instances of Hooks subclasses: {hook!r}")

        self.data_dir = Path(os.path.expanduser(data_dir))
        self._core = core = _Core(
            data_dir=self.data_dir,
            store=store or LocalStore(self.data_dir),
            secret_key=key_provider(secret_key),
            hooks=list(hooks),
            tokens=device_tokens or SqliteDeviceTokens(self.data_dir / "nodes" / "nodes.db"),
        )

        for node in nodes if nodes is not None else [Local()]:
            core.nodes.add(node)
        for name, provider in (node_providers or {}).items():
            core.nodes.add_provider(name, provider)
        for folder in shared_folders:
            core.nodes.add_shared_folder(folder)

        self.nodes = Nodes(core.nodes)

        for service in services:
            core.add_service(service)

        for service in _builtin_services():
            if not any(type(existing) is type(service) for existing in core.service_list):
                core.add_service(service)

        # When new_session doesn't specify an agent, choose only among directly registered Agents; subagents are registered too but don't count
        self._top_agents = [agent.name for agent in agents]

        for agent in agents:
            core.add_agent(agent)

        for model in models:
            core.models[model.id] = model
        for agent in core.agents.values():
            core.models.setdefault(agent.model.id, agent.model)

        self._runtime = Sessions(core)
        self._runtime.lifecycle.listen("session_closing", core.nodes.session_closing)

        self.extensions = Extensions(core, self._runtime)
        for toolset in extensions:
            self.extensions.add(toolset)

    def __repr__(self) -> str:
        return f"Runner({str(self.data_dir)!r})"

    @property
    def agents(self) -> list[Agent]:
        return list(self._core.agents.values())

    def service(self, kind: type) -> Any:
        """Return a registered service, e.g. runner.service(MCPService)."""
        return self._core.service(kind)

    async def start(self) -> None:
        """Start the Runner. If any step fails, shut down the started parts in reverse order, then re-raise the original exception."""
        if self._core.started:
            return

        core = self._core
        core.started_at = time.time()
        try:
            await core.store.open()
            await core.nodes.start()

            for service in core.service_list:
                await service.attach(self._runtime.api)

            self._core.started = True

            toolsets = [toolset for agent in core.agents.values() for toolset in agent.toolsets]
            for toolset in [*dict.fromkeys(toolsets), *self.extensions.list()]:
                await self._runtime.lifecycle.notify("toolset_added", toolset)

            await self._runtime.start()
        except BaseException:
            await self._close(runtime=self._core.started, quiet=True)
            raise

    async def shutdown(self) -> None:
        if not self._core.started:
            return
        await self._close(runtime=True, quiet=False)

    async def _close(self, *, runtime: bool, quiet: bool) -> None:
        steps = [self._runtime.shutdown] if runtime else []
        steps += [self._runtime.api.cancel_background, self._core.nodes.stop, self._core.store.close]
        try:
            for step in steps:
                if quiet:
                    with contextlib.suppress(Exception):
                        await step()
                else:
                    await step()
        finally:
            self._core.started = False

    async def __aenter__(self) -> Runner:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.shutdown()

    def _require_started(self) -> None:
        if not self._core.started:
            raise RuntimeError("The Runner hasn't started; use it inside async with runner, or call await runner.start() first")

    async def new_session(
        self,
        agent: Agent | str | None = None,
        *,
        workspace: Any = None,
        computer: Any = None,
        browser: Any = None,
        resources: dict[str, Any] | None = None,
        model: str | None = None,
        thinking: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        self._require_started()
        core = self._core

        if agent is None:
            top = [core.agents[name] for name in dict.fromkeys(self._top_agents)]
            if len(top) != 1:
                raise ConfigError("Multiple Agents are registered with the Runner; specify one with agent= in new_session")
            agent = top[0]

        name = agent.name if isinstance(agent, Agent) else agent
        core.agent(name)

        if isinstance(agent, Agent) and core.agents[name] is not agent:
            raise ConfigError(f"Agent {name} is not the same object that was registered; use the Agent instance you registered")

        given = dict(resources or {})
        for key, value in (("workspace", workspace), ("computer", computer), ("browser", browser)):
            if value is None:
                continue
            if key in given:
                raise ConfigError(f"Resource {key} specified more than once; specify it only once")
            given[key] = value

        config = SessionConfig(metadata=dict(metadata or {}))
        for key, value in given.items():
            provider = core.provider(key)
            if provider is None:
                raise ConfigError(f"No service provides resource {key!r}; register a Service with provides={key!r}")
            config.resources[key] = provider.config_of(value)

        if model is not None:
            core.model(model)
            config.model = model

        if thinking is not None:
            if thinking not in THINKING_LEVELS:
                raise ConfigError(f"Invalid thinking value; valid values are {THINKING_LEVELS}")
            config.thinking = thinking

        worker = await self._runtime.create(name, config)
        return Session(self._runtime, worker.session_id)

    async def session(self, session_id: str) -> Session:
        self._require_started()
        await self._runtime.worker(session_id)
        return Session(self._runtime, session_id)

    async def sessions(
        self, *, agent: str | None = None, status: str | None = None, top_level: bool = True
    ) -> list[Session]:
        self._require_started()
        records = await self._core.store.list_sessions(agent=agent, status=status, top_level=top_level)
        return [Session(self._runtime, record.id) for record in records]

    def events(self) -> AsyncIterator[Event]:
        return self._core.bus.stream()
