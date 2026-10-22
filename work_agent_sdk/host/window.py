from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

Item = tuple[int, bytes, Any]  # (起始字节编号, 数据, 附带信息：输出的流名，或输入的 None)


class SendWindow:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.acked = 0  # 对端已确认收到的字节数（缓冲区的起点）
        self.produced = 0  # 已交给窗口的总字节数（缓冲区的终点，也是下一个字节的编号）
        self.sent = 0  # 已交给当前连接发送的位置（仅输入方向的发送循环使用）
        self._buffer: list[Item] = []  # [acked, produced) 之间尚未确认的数据
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

    # 发送循环（输入方向）：沿 sent 指针取下一段发送；重连时 rewind 回到对端报告的位置重发
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
