from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import ipaddress
import os
import ssl
import struct
from urllib.parse import urlsplit

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_MESSAGE = 64 * 1024 * 1024
MAX_HEADER = 16 * 1024
TEXT = 0x1
CLOSE = 0x8
PING = 0x9
PONG = 0xA


class WebSocketClosed(ConnectionError):
    pass


def check_url(url: str) -> None:
    if urlsplit(url).scheme not in ("ws", "wss"):
        raise ValueError(f"The address must start with wss:// or ws://: {url}")


def is_loopback(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def apply_mask(data: bytes, mask: bytes) -> bytes:
    if not data:
        return data
    repeated = (mask * (len(data) // 4 + 1))[: len(data)]
    return (int.from_bytes(data, "big") ^ int.from_bytes(repeated, "big")).to_bytes(len(data), "big")


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


class WebSocket:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, client: bool = True) -> None:
        self.reader = reader
        self.writer = writer
        self.client = client
        self._write_lock = asyncio.Lock()

    @classmethod
    async def connect(cls, url: str, *, headers: dict[str, str] | None = None, timeout: float = 20) -> WebSocket:
        check_url(url)
        parts = urlsplit(url)
        secure = parts.scheme == "wss"
        port = parts.port or (443 if secure else 80)
        context = ssl.create_default_context() if secure else None
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                parts.hostname, port, ssl=context, server_hostname=parts.hostname if secure else None
            ),
            timeout,
        )
        key = base64.b64encode(os.urandom(16)).decode()
        host = f"[{parts.hostname}]" if ":" in (parts.hostname or "") else parts.hostname
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query

        extra = "".join(f"{name}: {value}\r\n" for name, value in (headers or {}).items())
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"{extra}"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        writer.write(request.encode())
        await writer.drain()
        response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout)
        status_line = response.split(b"\r\n", 1)[0].decode(errors="replace")
        if " 101 " not in status_line:
            writer.close()
            raise ConnectionError(f"WebSocket handshake failed: {status_line}")

        received = parse_headers(response)
        if received.get("sec-websocket-accept") != accept_key(key):
            writer.close()
            raise ConnectionError("WebSocket handshake verification failed")
        return cls(reader, writer)

    async def send_text(self, text: str) -> None:
        await self._send_frame(TEXT, text.encode())

    async def _send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytearray([0x80 | opcode])
        length = len(payload)
        mask_bit = 0x80 if self.client else 0
        if length < 126:
            header.append(mask_bit | length)
        elif length < 65536:
            header.append(mask_bit | 126)
            header += struct.pack(">H", length)
        else:
            header.append(mask_bit | 127)
            header += struct.pack(">Q", length)

        if self.client:
            mask = os.urandom(4)
            frame = bytes(header) + mask + apply_mask(payload, mask)
        else:
            frame = bytes(header) + payload

        async with self._write_lock:
            self.writer.write(frame)
            await self.writer.drain()

    async def receive_text(self) -> str:
        message = bytearray()
        while True:
            first, second = await self.reader.readexactly(2)
            final = bool(first & 0x80)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", await self.reader.readexactly(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", await self.reader.readexactly(8))[0]

            if len(message) + length > MAX_MESSAGE:
                raise WebSocketClosed(f"Message exceeds {MAX_MESSAGE} bytes")

            mask = await self.reader.readexactly(4) if second & 0x80 else None
            payload = await self.reader.readexactly(length)
            if mask is not None:
                payload = apply_mask(payload, mask)
            if opcode == CLOSE:
                raise WebSocketClosed("The peer closed the connection")
            if opcode == PING:
                await self._send_frame(PONG, payload)
                continue
            if opcode == PONG:
                continue

            message += payload
            if final:
                return message.decode()

    def abort(self) -> None:
        with contextlib.suppress(Exception):
            self.writer.transport.abort()

    async def close(self) -> None:
        try:
            await asyncio.wait_for(self._send_frame(CLOSE, b""), 5)
        except (TimeoutError, OSError):
            self.abort()
            return
        self.writer.close()


def parse_headers(raw: bytes) -> dict[str, str]:
    headers = {}
    for line in raw.decode(errors="replace").split("\r\n")[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
    return headers


async def accept_websocket(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, timeout: float = 15
) -> tuple[WebSocket, dict[str, str]] | None:
    try:
        raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout)
    except (TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        writer.close()
        return None

    if len(raw) > MAX_HEADER:
        writer.close()
        return None

    headers = parse_headers(raw)
    key = headers.get("sec-websocket-key")
    if headers.get("upgrade", "").lower() != "websocket" or not key:
        writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()
        return None
    return WebSocket(reader, writer, client=False), headers


async def finish_handshake(socket: WebSocket, headers: dict[str, str]) -> None:
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key(headers['sec-websocket-key'])}\r\n\r\n"
    )
    socket.writer.write(response.encode())
    await socket.writer.drain()


async def refuse_handshake(socket: WebSocket, status: str = "401 Unauthorized") -> None:
    socket.writer.write(f"HTTP/1.1 {status}\r\nContent-Length: 0\r\n\r\n".encode())
    await socket.writer.drain()
    socket.writer.close()
