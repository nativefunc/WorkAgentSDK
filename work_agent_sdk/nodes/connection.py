from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import TYPE_CHECKING, Any

from work_agent_sdk.core.errors import NodeOffline
from work_agent_sdk.core.utils import new_id
from work_agent_sdk.host.protocol import remote_error
from work_agent_sdk.host.window import SendWindow

if TYPE_CHECKING:
    from work_agent_sdk.nodes.hub import DeviceHub

# 超过该秒数未收到设备的任何消息，即视为断线
HEARTBEAT_TIMEOUT = 45
CALL_TIMEOUT = 120
# 单条消息的发送超时；网络阻塞时避免拖住该设备上的其他操作
SEND_TIMEOUT = 30
# 单次调用结果的大小上限，防止异常设备耗尽后端内存
MAX_RESULT_BYTES = 64 * 1024 * 1024
# 向设备发送命令输入时，最多留存的未确认数据；写满后暂停发送，等设备确认
INPUT_WINDOW = 4 * 1024 * 1024


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class DeviceStream:
    def __init__(self, stream_id: str, kind: str) -> None:
        self.id = stream_id
        self.kind = kind
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        # 已接收的输出字节数；重连后设备从此位置继续发送
        self.received = 0

        # 已向设备回执的输出位置（节流，避免每段都回执）
        self.acked_to_device = 0

        # 命令输入（后端 → 设备）的发送窗口；重连后从设备报告的位置重发
        self.input = SendWindow(INPUT_WINDOW)
        self.input_close_sent = False

        # 重连后由接入循环置位，唤醒并触发输入重发
        self.reconnected = asyncio.Event()


class DeviceConnection:
    def __init__(self, hub: DeviceHub, name: str, manifest: dict[str, Any], send: Any) -> None:
        self.hub = hub
        self.name = name
        self.manifest = manifest
        self._send = send
        self._send_lock = asyncio.Lock()
        self.calls: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self.parts: dict[str, list[str]] = {}
        self.last_seen = time.time()
        self.closed = asyncio.Event()

    @property
    def info(self) -> dict[str, Any]:
        manifest = self.manifest
        return {
            "online": not self.closed.is_set(),
            "os": manifest.get("os"),
            "shell": manifest.get("shell"),
            "home": manifest.get("home"),
            "workspace": manifest.get("workspace"),
            "screen": manifest.get("screen", False),
            "browser": manifest.get("browser", False),
            "paused": manifest.get("paused", False),
            "last_seen": self.last_seen,
        }

    async def send(self, message: dict[str, Any]) -> None:
        if self.closed.is_set():
            raise NodeOffline(self.name)

        text = json.dumps(message, ensure_ascii=False)
        try:
            async with self._send_lock:
                await asyncio.wait_for(self._send(text), SEND_TIMEOUT)
        except (TimeoutError, ConnectionError, OSError) as error:
            # 发送失败即视为连接断开：命令按断线处理，等待设备重新连接
            self.hub.connection_lost(self)
            raise NodeOffline(self.name, f"发送失败：{type(error).__name__}") from None

    def handle(self, message: dict[str, Any]) -> None:
        self.last_seen = time.time()
        kind = message.get("type")
        message_id = str(message.get("id") or "")

        if kind == "state":
            # 设备所有者暂停、恢复或急停时由设备上报
            self.manifest = {**self.manifest, **(message.get("manifest") or {})}
            return
        if kind == "result_part":
            if message_id in self.calls:
                parts = self.parts.setdefault(message_id, [])
                parts.append(message.get("data", ""))
                if sum(len(part) for part in parts) > MAX_RESULT_BYTES:
                    self.parts.pop(message_id, None)
                    future = self.calls.pop(message_id)
                    if not future.done():
                        future.set_exception(ValueError("设备回传的结果超过大小上限，已丢弃"))

            return

        if kind == "result":
            pending = self.calls.pop(message_id, None)
            parts = self.parts.pop(message_id, [])
            if "json" in message:
                message = {**message, "value": json.loads("".join(parts) + message["json"])}
            if pending is not None and not pending.done():
                pending.set_result(message)

            return

        stream = self.hub.stream(self.name, message_id)
        if stream is not None:
            stream.queue.put_nowait(message)

    async def call(self, op: str, timeout: float = CALL_TIMEOUT, **arguments: Any) -> Any:
        call_id = new_id("c_")
        future = asyncio.get_running_loop().create_future()
        self.calls[call_id] = future
        try:
            await self.send({"type": "call", "id": call_id, "op": op, "arguments": arguments})
            reply = await asyncio.wait_for(future, timeout)
        finally:
            self.calls.pop(call_id, None)
            self.parts.pop(call_id, None)

        error = reply.get("error")
        if error:
            raise remote_error(error)
        return reply.get("value")

    def disconnect(self) -> None:
        if self.closed.is_set():
            return

        self.closed.set()
        self.parts.clear()

        for future in self.calls.values():
            if not future.done():
                future.set_exception(NodeOffline(self.name, "连接已断开"))

        self.calls.clear()
