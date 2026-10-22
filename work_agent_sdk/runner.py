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
            raise ConfigError(f"Agent {name!r} 未在 Runner 中登记；请通过 Runner(agents=[...]) 登记")
        return agent

    def model(self, model_id: str) -> Any:
        model = self.models.get(model_id)
        if model is None:
            raise ConfigError(f"模型 {model_id!r} 未登记；请通过 Runner(models=[...]) 登记")
        return model

    def provider(self, resource: str) -> Service | None:
        return next((service for service in self.service_list if service.provides == resource), None)

    def services(self) -> list[Service]:
        return list(self.service_list)

    def service(self, kind: type) -> Any:
        for service in self.service_list:
            if isinstance(service, kind):
                return service
        raise ConfigError(f"Runner 上未登记服务 {kind.__name__}；请通过 Runner(services=[...]) 登记")

    def extensions(self) -> list[Toolset]:
        return list(self.toolsets.values())

    def publish(self, event: Event) -> None:
        self.bus.publish(event)

    def add_service(self, service: Service) -> None:
        if not isinstance(service, Service):
            raise ConfigError(f"services 须为 Service 子类的实例：{service!r}")
        if self.started:
            raise ConfigError("Runner 启动后不能再添加服务；请在启动前登记")
        if any(type(item) is type(service) for item in self.service_list):
            raise ConfigError(f"服务 {type(service).__name__} 重复登记；每种服务只能登记一个实例")
        if service.provides and any(item.provides == service.provides for item in self.service_list):
            raise ConfigError(f"资源 {service.provides!r} 已有提供者；每种资源只能由一个服务提供")

        self.service_list.append(service)

    def require_services(self, toolset: Toolset) -> None:
        for kind in unwrap(toolset).needs:
            if any(type(existing) is kind for existing in self.service_list):
                continue
            if self.started:
                raise ConfigError(f"工具集 {toolset.name} 依赖的服务 {kind.__name__} 未登记；请在 Runner 启动前登记")
            self.add_service(kind())

    def add_agent(self, agent: Agent) -> None:
        if not isinstance(agent, Agent):
            raise ConfigError(f"agents 须为 Agent 实例：{agent!r}")

        existing = self.agents.get(agent.name)
        if existing is not None:
            if existing is not agent:
                raise ConfigError(f"存在两个不同的 Agent 均名为 {agent.name}；请为其指定不同的名称")
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
            raise ConfigError(f"extensions 只接受 Toolset 实例：{toolset!r}")
        if toolset.hooks:
            raise ConfigError(f"extensions 中的工具集不能包含钩子：{toolset.name}；请将钩子登记到 Runner(hooks=[...])")
        if toolset.name in self._items:
            raise ConfigError(f"名为 {toolset.name} 的工具集已安装")

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
                raise ConfigError(f"hooks 须为 Hooks 子类的实例：{hook!r}")

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

        # new_session 未指定 agent 时只从直接登记的 Agent 中选择，子智能体虽然登记了但不算
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
        """返回登记的服务，例如 runner.service(MCPService)。"""
        return self._core.service(kind)

    async def start(self) -> None:
        """启动 Runner。任何一步失败时，按相反顺序关闭已启动的部分，再抛出原异常。"""
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
            raise RuntimeError("Runner 尚未启动；请在 async with runner 中使用，或先调用 await runner.start()")

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
                raise ConfigError("Runner 中登记了多个 Agent；请在 new_session 中通过 agent= 指定")
            agent = top[0]

        name = agent.name if isinstance(agent, Agent) else agent
        core.agent(name)

        if isinstance(agent, Agent) and core.agents[name] is not agent:
            raise ConfigError(f"Agent {name} 与登记的不是同一对象；请使用登记时的 Agent 实例")

        given = dict(resources or {})
        for key, value in (("workspace", workspace), ("computer", computer), ("browser", browser)):
            if value is None:
                continue
            if key in given:
                raise ConfigError(f"资源 {key} 重复指定；请只指定一次")
            given[key] = value

        config = SessionConfig(metadata=dict(metadata or {}))
        for key, value in given.items():
            provider = core.provider(key)
            if provider is None:
                raise ConfigError(f"没有服务提供资源 {key!r}；请登记 provides={key!r} 的 Service")
            config.resources[key] = provider.config_of(value)

        if model is not None:
            core.model(model)
            config.model = model

        if thinking is not None:
            if thinking not in THINKING_LEVELS:
                raise ConfigError(f"thinking 的取值无效；可选值为 {THINKING_LEVELS}")
            config.thinking = thinking

        worker = await self._runtime.create(name, config)
        return Session(self._runtime, worker.session_id)

    async def session(self, session_id: str) -> Session:
        """返回已有的会话；会话不存在时抛出 KeyError。"""
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
