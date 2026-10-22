from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import secrets
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from work_agent_sdk.core.errors import NodeOffline
from work_agent_sdk.core.events import (
    Event,
    NodeConnected,
    NodeDisconnected,
    NodeRefused,
)
from work_agent_sdk.core.utils import new_id
from work_agent_sdk.host.protocol import PROTOCOL_VERSION
from work_agent_sdk.host.websocket import WebSocket
from work_agent_sdk.nodes.connection import (
    HEARTBEAT_TIMEOUT,
    DeviceConnection,
    DeviceStream,
    token_digest,
)
from work_agent_sdk.nodes.tokens import DeviceTokens

if TYPE_CHECKING:
    from work_agent_sdk.nodes.device import Device

logger = logging.getLogger("work_agent_sdk")

DEFAULT_GRACE = 60
DIAL_DELAYS = (1, 2, 5, 10, 30)
REGISTER_TIMEOUT = 15


class DeviceHub:
    def __init__(
        self,
        tokens: DeviceTokens,
        publish: Callable[[Event], None],
        on_connected: Callable[[str], None],
    ) -> None:
        self.tokens = tokens
        self._publish = publish
        self._on_connected = on_connected
        self._devices: dict[str, Device] = {}
        self._connections: dict[str, DeviceConnection] = {}
        self._streams: dict[str, dict[str, DeviceStream]] = {}
        self._expiry: dict[str, asyncio.TimerHandle] = {}
        self._reconnected: dict[str, asyncio.Event] = {}
        self._dialers: dict[str, asyncio.Task] = {}
        self._watchdog: asyncio.Task | None = None
        self._running = False

    def attach(self, device: Device) -> None:
        self._devices[device.name] = device
        device.attach(self)
        if self._running:
            self._start_dialer(device.name)

    async def forget(self, name: str) -> None:
        self._devices.pop(name, None)
        dialer = self._dialers.pop(name, None)
        if dialer is not None:
            dialer.cancel()
            await asyncio.gather(dialer, return_exceptions=True)

        await self.tokens.delete(name)
        self._drop(name, grace=False)

    def grace(self, name: str) -> float:
        device = self._devices.get(name)
        return device.grace if device is not None else DEFAULT_GRACE

    async def start(self) -> None:
        self._running = True
        self._watchdog = asyncio.create_task(self._watch_heartbeats(), name="work_agent_sdk:nodes")
        for name in self._devices:
            self._start_dialer(name)

    async def stop(self) -> None:
        self._running = False
        tasks = [task for task in [self._watchdog, *self._dialers.values()] if task is not None]
        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        self._dialers.clear()

        for name in list(self._connections):
            self._drop(name, grace=False)

        await self.tokens.close()

    async def issue_token(self, name: str) -> str:
        token = secrets.token_urlsafe(32)
        await self.tokens.put(name, token_digest(token))

        # 重新签发即作废旧令牌，用旧令牌连接着的设备立即断开
        self._drop(name, grace=False)
        return token

    async def revoke(self, name: str) -> None:
        await self.tokens.delete(name)
        self._drop(name, grace=False)

    async def status(self) -> dict[str, dict[str, Any]]:
        names = set(await self.tokens.names()) | set(self._connections) | set(self._devices)
        result = {}
        for name in sorted(names):
            connection = self.connection(name)
            result[name] = connection.info if connection is not None else {"online": False}

        return result

    def connection(self, name: str) -> DeviceConnection | None:
        connection = self._connections.get(name)
        if connection is None or connection.closed.is_set():
            return None
        return connection

    async def wait_for(self, name: str, timeout: float) -> DeviceConnection | None:
        connection = self.connection(name)
        if connection is not None or timeout <= 0:
            return connection

        event = self._reconnected.setdefault(name, asyncio.Event())
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(event.wait(), timeout)

        return self.connection(name)

    async def send(self, name: str, message: dict[str, Any], *, wait: bool = False) -> None:
        connection = await self.wait_for(name, self.grace(name)) if wait else self.connection(name)
        if connection is None:
            raise NodeOffline(name)

        await connection.send(message)

    def open_stream(self, name: str, kind: str) -> DeviceStream:
        stream = DeviceStream(new_id("s_"), kind)
        self._streams.setdefault(name, {})[stream.id] = stream
        return stream

    def stream(self, name: str, stream_id: str | None) -> DeviceStream | None:
        return self._streams.get(name, {}).get(stream_id or "")

    def close_stream(self, name: str, stream_id: str) -> None:
        self._streams.get(name, {}).pop(stream_id, None)

    def connection_lost(self, connection: DeviceConnection) -> None:
        if self._connections.get(connection.name) is connection:
            self._drop(connection.name, grace=True)
        else:
            connection.disconnect()

    def _drop(self, name: str, *, grace: bool) -> None:
        connection = self._connections.pop(name, None)
        if connection is not None:
            connection.disconnect()
            self._publish(NodeDisconnected(node=name))

        streams = self._streams.get(name, {})
        for stream_id, stream in list(streams.items()):
            if stream.kind != "command":
                stream.queue.put_nowait({"type": "tcp_close", "id": stream_id})
                streams.pop(stream_id)

        handle = self._expiry.pop(name, None)
        if handle is not None:
            handle.cancel()

        # 命令流再保留 grace 秒：设备在此期间重连时，命令继续运行并补发输出
        if grace and streams:
            self._expiry[name] = asyncio.get_running_loop().call_later(self.grace(name), self._end_streams, name)
        else:
            self._end_streams(name)

    def _end_streams(self, name: str) -> None:
        self._expiry.pop(name, None)
        if self.connection(name) is not None:
            return

        for stream in self._streams.pop(name, {}).values():
            stream.queue.put_nowait({"type": "disconnected", "id": stream.id})

    async def websocket(self, websocket: Any) -> None:
        await websocket.accept()
        try:
            await self.connect(websocket.send_text, websocket.receive_text)
        finally:
            with contextlib.suppress(Exception):
                await websocket.close()

    async def connect(self, send: Any, receive: Any, *, expected: str | None = None) -> None:
        try:
            register = json.loads(await asyncio.wait_for(receive(), REGISTER_TIMEOUT))
        except Exception:
            return

        problem = await self._check_register(register, expected)
        if problem is None:
            await self._serve(register, send, receive)
            return

        with contextlib.suppress(Exception):
            await send(json.dumps({"type": "refused", "reason": problem}, ensure_ascii=False))

        logger.warning("已拒绝设备 %s：%s", register.get("name"), problem)

        if register.get("name"):
            self._publish(NodeRefused(node=str(register["name"]), detail={"reason": problem}))

    async def _serve(self, register: dict[str, Any], send: Any, receive: Any) -> None:
        name = register["name"]
        old = self._connections.get(name)
        other_instance = old is not None and old.manifest.get("instance") != register.get("instance")
        if old is not None and other_instance and time.time() - old.last_seen <= HEARTBEAT_TIMEOUT:
            # 原设备可能刚崩溃重启而旧连接尚未超时，因此允许对方稍后重试
            reason = f"设备名 {name} 已被另一台在线设备使用"
            with contextlib.suppress(Exception):
                await send(json.dumps({"type": "refused", "reason": reason, "retry": True}, ensure_ascii=False))

            logger.warning("已拒绝设备 %s：同名设备已在线", name)
            self._publish(NodeRefused(node=name, detail={"reason": reason}))
            return

        if old is not None:
            self._connections.pop(name, None)
            old.disconnect()

        handle = self._expiry.pop(name, None)
        if handle is not None:
            handle.cancel()

        manifest = {**(register.get("manifest") or {}), "instance": register.get("instance")}
        connection = DeviceConnection(self, name, manifest, send)
        self._connections[name] = connection
        self._on_connected(name)

        # 双方按对方已收到的位置续传：设备报告各命令收到的输入，后端回报各命令收到的输出
        command_streams = [stream for stream in self._streams.get(name, {}).values() if stream.kind == "command"]
        positions = register.get("commands") or {}
        for stream in command_streams:
            stream.input.rewind(positions.get(stream.id))
            stream.input_close_sent = False
            stream.reconnected.set()

        resume = {stream.id: stream.received for stream in command_streams}
        grace = self.grace(name)
        await send(json.dumps({"type": "registered", "version": PROTOCOL_VERSION, "resume": resume, "grace": grace}))
        event = self._reconnected.pop(name, None)
        if event is not None:
            event.set()

        logger.info("设备 %s 已连接", name)
        self._publish(NodeConnected(node=name, detail=connection.info))
        await self._receive_loop(name, connection, receive)

    async def _receive_loop(self, name: str, connection: DeviceConnection, receive: Any) -> None:
        closed = asyncio.create_task(connection.closed.wait())
        receiving: asyncio.Task | None = None
        reason = ""
        try:
            while True:
                receiving = asyncio.create_task(receive())
                done, _ = await asyncio.wait({receiving, closed}, return_when=asyncio.FIRST_COMPLETED)
                if receiving not in done or receiving.exception() is not None:
                    break

                try:
                    message = json.loads(receiving.result())
                    if message.get("type") != "ping":
                        connection.handle(message)
                        continue
                except Exception as error:
                    reason = f"消息无法处理（{type(error).__name__}: {error}）"
                    break

                connection.last_seen = time.time()
                await connection.send({"type": "pong"})
        except Exception:
            pass
        finally:
            closed.cancel()

            if receiving is not None:
                receiving.cancel()

            self.connection_lost(connection)

            if reason:
                logger.warning("设备 %s 已断开：%s", name, reason)
            else:
                logger.info("设备 %s 已断开", name)

    async def _check_register(self, register: dict[str, Any], expected: str | None) -> str | None:
        if register.get("type") != "register" or not register.get("name") or not register.get("token"):
            return "登记消息格式无效"

        name = register["name"]
        if expected is not None and name != expected:
            return f"连接到的设备为 {name}，而非预期的 {expected}"
        if register.get("version") != PROTOCOL_VERSION:
            version = register.get("version")
            return f"设备守护进程的协议版本 {version} 与后端的 {PROTOCOL_VERSION} 不一致；请升级至相同版本"

        given = token_digest(str(register["token"]))
        device = self._devices.get(name)
        configured = device.token if device is not None and expected is not None else None
        if configured:
            return None if hmac.compare_digest(token_digest(configured), given) else "令牌无效"

        stored = await self.tokens.get(name)
        if stored is None or not hmac.compare_digest(stored, given):
            return "令牌无效"
        return None

    def _start_dialer(self, name: str) -> None:
        device = self._devices.get(name)
        if device is None or not device.connect_url or name in self._dialers:
            return

        self._dialers[name] = asyncio.create_task(self._dial(name), name=f"work_agent_sdk:dial:{name}")

    async def _dial(self, name: str) -> None:
        attempt = 0
        while True:
            device = self._devices.get(name)
            url = device.connect_url if device is not None else None
            if not url:
                return

            socket = None
            try:
                socket = await WebSocket.connect(url, headers={"Authorization": f"Bearer {device.token}"})
                attempt = 0
                await self.connect(socket.send_text, socket.receive_text, expected=name)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.debug("无法连接设备 %s：%s", name, error)
            finally:
                if socket is not None:
                    await socket.close()

            await asyncio.sleep(DIAL_DELAYS[min(attempt, len(DIAL_DELAYS) - 1)])
            attempt += 1

    async def _watch_heartbeats(self) -> None:
        while True:
            await asyncio.sleep(5)
            moment = time.time()
            for name, connection in list(self._connections.items()):
                if moment - connection.last_seen > HEARTBEAT_TIMEOUT:
                    logger.warning("设备 %s 已 %d 秒无心跳，视为断线", name, HEARTBEAT_TIMEOUT)
                    self._drop(name, grace=True)
