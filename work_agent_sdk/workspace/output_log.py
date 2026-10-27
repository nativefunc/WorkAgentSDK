from __future__ import annotations

import asyncio
import codecs
import contextlib
import os
import re


def decode_utf8_prefix(data: bytes, *, final: bool) -> tuple[str, int]:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    text = decoder.decode(data, final=final)
    pending = len(decoder.getstate()[0])
    return text, len(data) - pending


PROCESS_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class OutputLog:
    def __init__(self, directory: str) -> None:
        self.directory = os.path.abspath(os.path.expanduser(directory))

    def path(self, process_id: str) -> str:
        if not PROCESS_ID.match(process_id):
            raise ValueError(f"Invalid process ID: {process_id!r}")
        return os.path.join(self.directory, f"{process_id}.log")

    async def append(self, process_id: str, data: bytes) -> None:
        await asyncio.to_thread(self._append, self.path(process_id), data)

    def _append(self, path: str, data: bytes) -> None:
        os.makedirs(self.directory, exist_ok=True)
        with open(path, "ab") as file:
            file.write(data)

    def size(self, process_id: str) -> int:
        try:
            return os.path.getsize(self.path(process_id))
        except FileNotFoundError:
            return 0

    async def read(self, process_id: str, start: int, end: int) -> bytes:
        if end <= start:
            return b""
        return await asyncio.to_thread(self._read, self.path(process_id), start, end)

    @staticmethod
    def _read(path: str, start: int, end: int) -> bytes:
        try:
            with open(path, "rb") as file:
                file.seek(start)
                return file.read(end - start)
        except FileNotFoundError:
            return b""

    async def remove(self, process_id: str) -> None:
        def remove() -> None:
            with contextlib.suppress(FileNotFoundError):
                os.remove(self.path(process_id))

        await asyncio.to_thread(remove)
