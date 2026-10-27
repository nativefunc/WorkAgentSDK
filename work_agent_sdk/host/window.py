from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

Item = tuple[int, bytes, Any]  # (starting byte number, data, extra info: the stream name for output, or None for input)


class SendWindow:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.acked = 0  # Bytes the peer has acknowledged (start of the buffer)
        self.produced = 0  # Total bytes handed to the window (end of the buffer, also the number of the next byte)
        self.sent = 0  # Position handed to the current connection for sending (only used by the input-direction send loop)
        self._buffer: list[Item] = []  # Unacknowledged data between [acked, produced)
        self._room = asyncio.Event()
        self._room.set()
        self._work = asyncio.Event()

    @property
    def pending(self) -> int:
        return self.produced - self.acked

    def add(self, data: bytes, meta: Any = None) -> int:
        offset = self.produced
        if data:
            self._buffer.append((offset, data, meta))
            self.produced += len(data)
            if self.pending >= self.limit:
                self._room.clear()

            self._work.set()

        return offset

    def ack(self, received: int) -> None:
        self.acked = max(self.acked, min(received, self.produced))
        while self._buffer and self._buffer[0][0] + len(self._buffer[0][1]) <= self.acked:
            self._buffer.pop(0)

        if self.pending < self.limit:
            self._room.set()

    def items_from(self, start: int) -> Iterator[Item]:
        for offset, data, meta in list(self._buffer):
            end = offset + len(data)
            if end <= start:
                continue
            if offset < start:
                yield start, data[start - offset :], meta
            else:
                yield offset, data, meta

    # Send loop (input direction): take the next chunk after the sent pointer; on reconnect, rewind to the position the peer reported and resend
    def rewind(self, to: int | None) -> None:
        self.sent = self.acked if to is None else max(self.acked, min(to, self.produced))
        if self.sent < self.produced:
            self._work.set()

    def pull(self) -> Item | None:
        for offset, data, meta in self._buffer:
            end = offset + len(data)
            if end <= self.sent:
                continue

            start = max(self.sent, offset)
            self.sent = end
            return start, data[start - offset :], meta

        if self.sent >= self.produced:
            self._work.clear()

        return None

    def all_sent(self) -> bool:
        return self.sent >= self.produced

    def fully_acked(self) -> bool:
        return self.acked >= self.produced

    async def wait_room(self) -> None:
        await self._room.wait()

    async def wait_work(self) -> None:
        await self._work.wait()

    def notify(self) -> None:
        self._work.set()
