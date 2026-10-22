from __future__ import annotations

import asyncio
import base64
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

import work_agent_sdk.host.protocol as protocol
from work_agent_sdk.core.errors import ConfigError, NodeOffline
from work_agent_sdk.core.utils import expand_env, has_env_reference
from work_agent_sdk.host.browser import BrowserOptions
from work_agent_sdk.host.commands.process import OutputChunk, Stdin
from work_agent_sdk.host.commands.run import Command
from work_agent_sdk.host.commands.sandbox import NodeSandbox
from work_agent_sdk.nodes.base import Node, NodeInfo, PortForward
from work_agent_sdk.nodes.connection import DeviceConnection

if TYPE_CHECKING:
    from work_agent_sdk.nodes.hub import DeviceHub

# 每累积这么多字节向设备回执一次输出接收位置
OUTPUT_ACK_INTERVAL = 256 * 1024


class Device(Node):
    """远程设备节点。离线时调用 wake 并最多等待 wait 秒；断线后 grace 秒内重连，设备上的命令继续运行。"""

    def __init__(
        self,
        name: str,
        *,
        connect: str | None = None,
        token: str | None = None,
        wake: Callable[[], Awaitable[None] | None] | None = None,
        wait: float = 60,
        grace: float = 60,
    ) -> None:
        super().__init__()

        if not name:
            raise ConfigError('Device 缺少名称；请传入 name，例如 Device("gpu-a")')
        if connect is not None and not token:
            raise ConfigError("后端主动连接设备（connect=）时缺少 token；请传入设备守护进程使用的令牌")

        self.name = name
        self.connect_target = connect
        self._token = token
        self.wake = wake
        self.wait = wait

        # 断线后等待重连的秒数：期间设备上的命令继续运行，重连后补发输出
        self.grace = grace
        self._hub: DeviceHub | None = None

    def __repr__(self) -> str:
        return f"Device({self.name!r})"

    @property
    def connect_url(self) -> str | None:
        target = self.connect_target
        return expand_env(target) if target and has_env_reference(target) else target

    @property
    def token(self) -> str | None:
        token = self._token
        return expand_env(token) if token and has_env_reference(token) else token

    def attach(self, hub: DeviceHub) -> None:
        self._hub = hub

    @property
    def hub(self) -> DeviceHub:
        if self._hub is None:
            raise RuntimeError("Device 尚未登记；请先通过 Runner(nodes=[...]) 或 runner.nodes.add() 登记")
        return self._hub

    def connection(self) -> DeviceConnection:
        connection = self.hub.connection(self.name)
        if connection is None:
            raise NodeOffline(self.name)
        return connection

    @property
    def manifest(self) -> dict[str, Any]:
        return self.connection().manifest

    async def _call(self, call: protocol.Call) -> Any:
        return await self.connection().call(call.op, **call.arguments())

    async def info(self) -> NodeInfo:
        return self._info_from(self.manifest)

    def known_info(self) -> NodeInfo | None:
        connection = self._hub.connection(self.name) if self._hub is not None else None
        return self._info_from(connection.manifest) if connection is not None else None

    @staticmethod
    def _info_from(manifest: dict[str, Any]) -> NodeInfo:
        workspace = manifest.get("workspace") or {}
        declared = workspace.get("sandbox")
        return NodeInfo(
            os=manifest.get("os", "linux"),
            shell=manifest.get("shell", "bash"),
            home=manifest.get("home", "~"),
            commands=bool(declared),
            sandbox=NodeSandbox.model_validate(declared) if declared else None,
            roots=[str(root["path"]) for root in workspace.get("roots") or []],
        )

    async def check_workspace(self, path: str) -> None:
        workspace = self.manifest.get("workspace")
        if not workspace:
            raise ConfigError(f"设备 {self.name} 未开放工作区；请在设备守护进程启动时添加 --workspace <目录>")

        style = (await self.info()).style
        for root in workspace.get("roots", []):
            if style.inside(path, root["path"]):
                return

        roots = [root["path"] for root in workspace.get("roots", [])]
        raise ConfigError(f"{path} 不在设备 {self.name} 开放的目录中；开放的目录为 {roots}")

    async def exec(self, command: Command, stdin: Stdin = None) -> AsyncIterator[OutputChunk]:
        hub = self.hub
        name = self.name
        stream = hub.open_stream(name, "command")
        feeder: asyncio.Task | None = None
        finished = False
        try:
            await hub.send(
                name,
                {
                    "type": "command",
                    "id": stream.id,
                    "command": command.model_dump(mode="json"),
                    "stdin": stdin is not None,
                },
            )

            if stdin is not None:
                feeder = asyncio.create_task(self._feed(stream, stdin))

            while True:
                message = await stream.queue.get()
                kind = message["type"]
                if kind == "output":
                    data = base64.b64decode(message["data"])
                    offset = message.get("offset", stream.received)
                    end = offset + len(data)
                    if end <= stream.received:
                        continue  # 重连补发中已接收过的部分

                    if offset > stream.received:
                        # 可靠通道下设备总从本端已收到的位置续发，不应出现缺口；真的出现则如实注明，不猜原因
                        gap = offset - stream.received
                        stream.received = offset
                        yield OutputChunk("stderr", f"\n[有 {gap} 字节输出缺失]\n".encode())

                    data = data[stream.received - offset :]
                    stream.received = end
                    yield OutputChunk(message["stream"], data)
                    await self._ack_output(stream)
                elif kind == "stdin_ack":
                    stream.input.ack(int(message.get("received", 0)))
                    stream.input.notify()
                elif kind == "exit":
                    total = message.get("output")
                    if isinstance(total, int) and stream.received < total:
                        yield OutputChunk("stderr", f"\n[有 {total - stream.received} 字节输出未送达]\n".encode())

                    finished = True
                    yield OutputChunk("exit", code=message.get("code"))
                    return
                elif kind == "disconnected":
                    raise NodeOffline(name, "连接断开后未在宽限时间内重新连接")
        finally:
            if feeder is not None:
                feeder.cancel()
                await asyncio.gather(feeder, return_exceptions=True)
            hub.close_stream(name, stream.id)
            if not finished:
                with contextlib.suppress(Exception):
                    await hub.send(name, {"type": "cancel", "id": stream.id})

    async def _ack_output(self, stream: Any) -> None:
        if stream.received - stream.acked_to_device < OUTPUT_ACK_INTERVAL:
            return

        stream.acked_to_device = stream.received
        with contextlib.suppress(Exception):
            await self.hub.send(self.name, {"type": "ack", "id": stream.id, "received": stream.received})

    async def _feed(self, stream: Any, stdin: Any) -> None:
        name = self.name
        window = stream.input
        done = asyncio.Event()

        async def produce() -> None:
            try:
                if isinstance(stdin, (bytes, bytearray)):
                    await window.wait_room()
                    window.add(bytes(stdin))
                else:
                    async for piece in stdin:
                        await window.wait_room()
                        window.add(bytes(piece))
            finally:
                done.set()
                window.notify()

        producer = asyncio.create_task(produce())
        try:
            while True:
                if stream.reconnected.is_set():
                    stream.reconnected.clear()

                while (item := window.pull()) is not None:
                    offset, data, _ = item
                    await self.hub.send(
                        name,
                        {"type": "stdin", "id": stream.id, "offset": offset, "data": base64.b64encode(data).decode()},
                        wait=True,
                    )

                if done.is_set() and window.all_sent() and not stream.input_close_sent:
                    await self.hub.send(
                        name, {"type": "stdin_close", "id": stream.id, "total": window.produced}, wait=True
                    )
                    stream.input_close_sent = True

                waiters = [
                    asyncio.ensure_future(window.wait_work()),
                    asyncio.ensure_future(stream.reconnected.wait()),
                ]
                try:
                    await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for waiter in waiters:
                        waiter.cancel()
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)

    async def file_op(self, op: str, **arguments: Any) -> Any:
        return await self._call(protocol.FileOp(file_op=op, arguments_=arguments))

    async def read_block(self, path: str, offset: int, size: int) -> bytes:
        return base64.b64decode(await self._call(protocol.ReadBlock(path=path, offset=offset, size=size)))

    async def write_block(self, path: str, offset: int, data: bytes) -> None:
        encoded = base64.b64encode(data).decode()
        await self._call(protocol.WriteBlock(path=path, offset=offset, data=encoded))

    async def tree_hash(self, path: str) -> str | None:
        return await self._call(protocol.TreeHashCall(path=path))

    async def find_manifests(
        self,
        workspace: str,
        roots: list[str],
        manifest: str,
        max_size: int,
        *,
        unchanged: str | None = None,
        read: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        call = protocol.FindManifests(
            workspace=workspace, roots=roots, manifest=manifest, max_size=max_size, unchanged=unchanged, read=list(read)
        )
        return dict(await self._call(call))

    async def start_browser(self, options: BrowserOptions) -> int:
        if not self.manifest.get("browser"):
            raise PermissionError(f"设备 {self.name} 未开放浏览器；请在设备守护进程启动时添加 --browser")
        return int(await self._call(protocol.BrowserStart(options=options.model_dump(mode="json"))))

    async def stop_browser(self, profile: str) -> None:
        await self._call(protocol.BrowserStop(profile=profile))

    async def forward_port(self, port: int) -> PortForward:
        forward = DevicePortForward(self, port)
        await forward.start()
        return forward

    def screen_display(self, requested: str | None) -> str | None:
        return requested or next(iter(self.manifest.get("displays") or []), None)

    async def computer(self, op: str, display: str | None = None, **arguments: Any) -> Any:
        if not self.manifest.get("screen"):
            raise PermissionError(f"设备 {self.name} 未开放屏幕；请在设备守护进程启动时添加 --screen")
        return await self._call(protocol.ComputerCall(display=display, computer_op=op, arguments_=arguments))


class DevicePortForward(PortForward):
    # 设备只放行由它自己启动的浏览器

    def __init__(self, node: Device, remote_port: int) -> None:
        self.node = node
        self.remote_port = remote_port
        self._server: asyncio.base_events.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, 0)
        self.local_port = self._server.sockets[0].getsockname()[1]

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        hub = self.node.hub
        name = self.node.name
        stream = hub.open_stream(name, "tcp")

        async def upstream() -> None:
            while data := await reader.read(65536):
                await hub.send(name, {"type": "tcp_data", "id": stream.id, "data": base64.b64encode(data).decode()})
            await hub.send(name, {"type": "tcp_close", "id": stream.id})

        sender: asyncio.Task | None = None
        try:
            await hub.send(name, {"type": "tcp_open", "id": stream.id, "port": self.remote_port})
            sender = asyncio.create_task(upstream())

            while True:
                message = await stream.queue.get()
                if message["type"] != "tcp_data":
                    break

                writer.write(base64.b64decode(message["data"]))
                await writer.drain()
        except Exception:
            pass
        finally:
            if sender is not None:
                sender.cancel()
            hub.close_stream(name, stream.id)
            with contextlib.suppress(Exception):
                writer.close()

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
