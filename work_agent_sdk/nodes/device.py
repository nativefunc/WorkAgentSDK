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
from work_agent_sdk.host.screen.policy import DeviceCeiling
from work_agent_sdk.nodes.base import Node, NodeInfo, PortForward
from work_agent_sdk.nodes.connection import DeviceConnection

if TYPE_CHECKING:
    from work_agent_sdk.nodes.hub import DeviceHub

# Acknowledge the output receive position to the device every time this many bytes accumulate
OUTPUT_ACK_INTERVAL = 256 * 1024


class Device(Node):
    """A remote device node. When offline, wake is called and up to wait seconds are spent waiting; if it reconnects within grace seconds after a disconnect, commands on the device keep running."""

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
            raise ConfigError('Device is missing a name; pass name, e.g. Device("gpu-a")')
        if connect is not None and not token:
            raise ConfigError("token is missing when the backend connects to the device (connect=); pass the token the device daemon uses")

        self.name = name
        self.connect_target = connect
        self._token = token
        self.wake = wake
        self.wait = wait

        # Seconds to wait for a reconnect after a disconnect: commands on the device keep running meanwhile, and output is resent after reconnecting
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
            raise RuntimeError("Device isn't registered yet; register it first with Runner(nodes=[...]) or runner.nodes.add()")
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
        ceiling = manifest.get("screen_ceiling")
        return NodeInfo(
            os=manifest.get("os", "linux"),
            shell=manifest.get("shell", "bash"),
            home=manifest.get("home", "~"),
            commands=bool(declared),
            sandbox=NodeSandbox.model_validate(declared) if declared else None,
            roots=[str(root["path"]) for root in workspace.get("roots") or []],
            screen_ceiling=DeviceCeiling.model_validate(ceiling) if ceiling else None,
        )

    async def check_workspace(self, path: str) -> None:
        workspace = self.manifest.get("workspace")
        if not workspace:
            raise ConfigError(f"Device {self.name} doesn't expose a workspace; add --workspace <directory> when starting the device daemon")

        style = (await self.info()).style
        for root in workspace.get("roots", []):
            if style.inside(path, root["path"]):
                return

        roots = [root["path"] for root in workspace.get("roots", [])]
        raise ConfigError(f"{path} is not inside a directory exposed by device {self.name}; exposed directories are {roots}")

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
                        continue  # Part already received during the reconnect replay

                    if offset > stream.received:
                        # The device resumes from the position the backend has received, so normally there's no gap; if there is one, note the number of missing bytes in the output
                        gap = offset - stream.received
                        stream.received = offset
                        yield OutputChunk("stderr", f"\n[{gap} bytes of output missing]\n".encode())

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
                        yield OutputChunk("stderr", f"\n[{total - stream.received} bytes of output not delivered]\n".encode())

                    finished = True
                    yield OutputChunk("exit", code=message.get("code"))
                    return
                elif kind == "disconnected":
                    raise NodeOffline(name, "didn't reconnect within the grace period after the connection dropped")
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
                        {
                            "type": "stdin",
                            "id": stream.id,
                            "offset": offset,
                            "data": base64.b64encode(data).decode(),
                        },
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
            raise PermissionError("The device doesn't expose a browser")
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
            raise PermissionError("The device doesn't expose its screen")
        return await self._call(protocol.ComputerCall(display=display, computer_op=op, arguments_=arguments))


class DevicePortForward(PortForward):
    # The device only allows browsers it started itself

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
