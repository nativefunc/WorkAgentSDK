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

# If no message at all arrives from the device for this many seconds, it is considered disconnected
HEARTBEAT_TIMEOUT = 45
CALL_TIMEOUT = 120
# Send timeout for a single message; avoids holding up other operations on this device when the network is congested
SEND_TIMEOUT = 30
# Size limit for a single call result, so a misbehaving device can't exhaust the backend's memory
MAX_RESULT_BYTES = 64 * 1024 * 1024
# Maximum unacknowledged data kept when sending command input to the device; sending pauses when full until the device acknowledges
INPUT_WINDOW = 4 * 1024 * 1024


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class DeviceStream:
    def __init__(self, stream_id: str, kind: str) -> None:
        self.id = stream_id
        self.kind = kind
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        # Output bytes received; after reconnecting the device continues sending from this position
        self.received = 0

        # Output position acknowledged to the device (throttled, to avoid acknowledging every chunk)
        self.acked_to_device = 0

        # Send window for command input (backend → device); after reconnecting, resend from the position the device reports
        self.input = SendWindow(INPUT_WINDOW)
        self.input_close_sent = False

        # Set by the accept loop after reconnecting, to wake up and trigger resending input
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
            # A send failure means the connection dropped: commands are handled as disconnected while waiting for the device to reconnect
            self.hub.connection_lost(self)
            raise NodeOffline(self.name, f"send failed: {type(error).__name__}") from None

    def handle(self, message: dict[str, Any]) -> None:
        self.last_seen = time.time()
        kind = message.get("type")
        message_id = str(message.get("id") or "")

        if kind == "state":
            # Reported by the device when its owner pauses, resumes or emergency-stops
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
                        future.set_exception(ValueError("The result sent back by the device exceeds the size limit and was discarded"))

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
                future.set_exception(NodeOffline(self.name, "connection dropped"))

        self.calls.clear()
