from __future__ import annotations

import asyncio
import contextlib
import inspect
from collections.abc import Callable, Collection
from typing import Any, Protocol

from work_agent_sdk.core.errors import ConfigError, NodeOffline
from work_agent_sdk.core.events import Event
from work_agent_sdk.core.service import SessionRef
from work_agent_sdk.nodes.base import Node, NodeInfo
from work_agent_sdk.nodes.device import Device
from work_agent_sdk.nodes.files import LazyFiles, NodeHost, ScopedFiles
from work_agent_sdk.nodes.hub import DeviceHub
from work_agent_sdk.nodes.shared import SharedFolder
from work_agent_sdk.nodes.tokens import DeviceTokens


class NodeProvider(Protocol):
    isolated: bool

    async def acquire(self, root_id: str) -> Node: ...

    async def release(self, root_id: str) -> None: ...


class NodeRegistry:
    def __init__(self, tokens: DeviceTokens, publish: Callable[[Event], None]) -> None:
        self.hub = DeviceHub(tokens, publish, on_connected=self._connected)
        self._nodes: dict[str, Node] = {}
        self._providers: dict[str, NodeProvider] = {}
        self._shared: dict[str, SharedFolder] = {}

        # 顶层会话 -> [(提供者名, 为该会话树创建的节点名)]
        self._trees: dict[str, list[tuple[str, str]]] = {}
        self._acquiring: dict[tuple[str, str], asyncio.Lock] = {}
        self._started: set[str] = set()
        self._info: dict[str, NodeInfo] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def __contains__(self, name: str) -> bool:
        return name in self._nodes

    def names(self) -> list[str]:
        return sorted(self._nodes)

    def add(self, node: Node, name: str | None = None) -> Node:
        name = name or node.name
        if not name:
            raise ConfigError("节点缺少名称；请在登记时指定 name")

        existing = self._nodes.get(name)
        if existing is not None and existing is not node:
            raise ConfigError(f"名为 {name} 的节点已登记；请使用其他名称")

        node.name = name
        self._nodes[name] = node
        if isinstance(node, Device):
            self.hub.attach(node)

        return node

    async def remove(self, name: str) -> None:
        node = self._nodes.pop(name, None)
        await self.hub.forget(name)
        self._info.pop(name, None)

        if node is not None and name in self._started:
            self._started.discard(name)
            with contextlib.suppress(Exception):
                await node.close()

    def add_provider(self, name: str, provider: NodeProvider) -> None:
        if name in self._nodes or name in self._providers:
            raise ConfigError(f"名为 {name} 的节点已登记；请使用其他名称")
        self._providers[name] = provider

    def add_shared_folder(self, folder: SharedFolder) -> None:
        if folder.name in self._shared:
            raise ConfigError(f"名为 {folder.name} 的共享文件夹已声明；请使用其他名称")

        for node in folder.mounts:
            if not self.known(node):
                raise ConfigError(f"共享文件夹 {folder.name} 引用的节点 {node!r} 未登记")

        self._shared[folder.name] = folder

    def shared_folders(self, name: str) -> list[tuple[str, str]]:
        return [(folder.name, folder.mounts[name]) for folder in self._shared.values() if name in folder.mounts]

    def known(self, name: str) -> bool:
        return name in self._providers or name in self._nodes

    def isolated(self, name: str) -> bool:
        provider = self._providers.get(name)
        return bool(provider is not None and provider.isolated)

    def node(self, name: str) -> Node:
        node = self._nodes.get(name)
        if node is None:
            raise ConfigError(f"节点 {name!r} 未登记；请通过 Runner(nodes=[...]) 或 runner.nodes.add() 登记")
        return node

    def files(self, name: str) -> LazyFiles:
        async def open_files() -> ScopedFiles:
            host = await self.ready(name)
            info = await self.info(name)
            files = NodeHost(host, info.style, info.node_paths.transfers)
            return ScopedFiles(files, style=info.style, home=info.home, keep=[info.home])

        return LazyFiles(open_files)

    async def get(self, name: str, *, root_id: str, wait: bool = True) -> Node:
        if not self.known(name):
            raise ConfigError(f"节点 {name!r} 未登记")

        instance = await self._tree_instance(name, root_id)
        if not wait and not self.is_online(instance):
            raise NodeOffline(name)
        return await self.ready(instance)

    def online(self, name: str, *, root_id: str) -> bool | None:
        if name in self._providers:
            instance = self._acquired(name, root_id)
            return self.is_online(instance) if instance is not None else None
        return self.is_online(name)

    def cached_info(self, name: str, *, root_id: str | None = None) -> NodeInfo | None:
        if name in self._providers:
            if root_id is None:
                return None
            instance = self._acquired(name, root_id)
            if instance is None:
                return None
            name = instance

        info = self._info.get(name)
        node = self._nodes.get(name)
        if info is None and node is not None:
            info = node.known_info()
        return info

    def is_online(self, name: str) -> bool:
        if name in self._providers:
            return True

        node = self._nodes.get(name)
        if node is None:
            return False
        return not isinstance(node, Device) or self.hub.connection(name) is not None

    async def ready(self, name: str) -> Node:
        node = self.node(name)
        async with self._locks.setdefault(name, asyncio.Lock()):
            if name not in self._started:
                await node.start()
                self._started.add(name)

            if isinstance(node, Device) and self.hub.connection(name) is None:
                if node.wake is not None:
                    result = node.wake()
                    if inspect.isawaitable(result):
                        await result
                if await self.hub.wait_for(name, node.wait) is None:
                    raise NodeOffline(name)

        return node

    async def info(self, name: str) -> NodeInfo:
        node = await self.ready(name)
        if name not in self._info:
            self._info[name] = await node.info()
        return self._info[name]

    async def start(self) -> None:
        await self.hub.start()

    async def stop(self) -> None:
        await self.hub.stop()

        for name in list(self._started):
            with contextlib.suppress(Exception):
                await self._nodes[name].close()

        self._started.clear()
        self._info.clear()

    async def session_closing(self, session: SessionRef) -> None:
        if session.parent_id is None:
            names = {str(config.get("node")) for config in session.resources.values() if isinstance(config, dict)}
            await self.release_tree(session.id, names)

    async def release_tree(self, root_id: str, names: Collection[str] = frozenset()) -> None:
        acquired = self._trees.pop(root_id, [])
        for _, instance in acquired:
            await self.remove(instance)
        for name, _ in acquired:
            self._acquiring.pop((name, root_id), None)

        # 节点可能由上一个进程创建，本进程即使没有 acquire 过也要通知提供者释放
        for name in {name for name, _ in acquired} | {name for name in names if name in self._providers}:
            with contextlib.suppress(Exception):
                await self._providers[name].release(root_id)

    def _connected(self, name: str) -> None:
        # 设备重新连接后可能换了配置（开放的目录、系统），不再沿用旧的节点信息
        self._info.pop(name, None)

    def _acquired(self, name: str, root_id: str) -> str | None:
        for provider, instance in self._trees.get(root_id, []):
            if provider == name:
                return instance
        return None

    async def _tree_instance(self, name: str, root_id: str) -> str:
        provider = self._providers.get(name)
        if provider is None:
            return name

        async with self._acquiring.setdefault((name, root_id), asyncio.Lock()):
            instance = self._acquired(name, root_id)
            if instance is None:
                node = await provider.acquire(root_id)
                instance = _instance_name(name, root_id, node)
                if instance in self._nodes or instance in self._providers:
                    raise ConfigError(
                        f"节点提供者 {name} 为会话树 {root_id} 返回的节点名为 {instance}，"
                        "该名称已被其他节点或其他会话树使用；每个会话树的设备名称须各不相同"
                    )

                self.add(node, instance)
                self._trees.setdefault(root_id, []).append((name, instance))

        return instance


def _instance_name(provider: str, root_id: str, node: Node) -> str:
    # 设备按守护进程登记的名称接入、令牌也按该名称签发，只能用设备自己的名称
    if isinstance(node, Device):
        if not node.name:
            raise ConfigError(f"节点提供者 {provider} 为会话树 {root_id} 返回的设备没有名称")
        return node.name
    return f"{provider}/{root_id}"


class Nodes:
    def __init__(self, registry: NodeRegistry) -> None:
        self._registry = registry

    def __repr__(self) -> str:
        return f"Nodes({self.names()})"

    def __contains__(self, name: str) -> bool:
        return name in self._registry

    def names(self) -> list[str]:
        return self._registry.names()

    def add(self, node: Node, name: str | None = None) -> Node:
        return self._registry.add(node, name)

    async def remove(self, name: str) -> None:
        await self._registry.remove(name)

    def add_provider(self, name: str, provider: NodeProvider) -> None:
        self._registry.add_provider(name, provider)

    def add_shared_folder(self, folder: SharedFolder) -> None:
        self._registry.add_shared_folder(folder)

    def is_online(self, name: str) -> bool:
        return self._registry.is_online(name)

    def files(self, name: str) -> LazyFiles:
        return self._registry.files(name)

    async def issue_token(self, name: str) -> str:
        return await self._registry.hub.issue_token(name)

    async def revoke(self, name: str) -> None:
        await self._registry.hub.revoke(name)

    async def status(self) -> dict[str, dict[str, Any]]:
        return await self._registry.hub.status()

    async def websocket(self, websocket: Any) -> None:
        await self._registry.hub.websocket(websocket)

    async def connect(self, send: Any, receive: Any) -> None:
        await self._registry.hub.connect(send, receive)
