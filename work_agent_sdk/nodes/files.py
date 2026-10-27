from __future__ import annotations

import builtins
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Iterable
from typing import TYPE_CHECKING, Any, Protocol

import work_agent_sdk.nodes.transfer as transfer
from work_agent_sdk.host.files.info import FileInfo
from work_agent_sdk.host.files.paths import PathStyle
from work_agent_sdk.nodes.transfer import DEFAULT_MAX_SIZE

if TYPE_CHECKING:
    from work_agent_sdk.nodes.base import Node


class FileHost(Protocol):
    async def op(self, name: str, **arguments: Any) -> Any: ...

    def read(self, path: str, max_size: int | None) -> AsyncIterator[bytes]: ...

    async def write(self, path: str, data: bytes | AsyncIterable[bytes], max_size: int | None) -> dict[str, Any]: ...


class NodeHost:
    def __init__(self, node: Node, style: PathStyle, directory: str) -> None:
        self._node = node
        self._style = style
        self._directory = directory

    async def op(self, name: str, **arguments: Any) -> Any:
        return await self._node.file_op(name, **arguments)

    async def read(self, path: str, max_size: int | None) -> AsyncIterator[bytes]:
        async for piece in transfer.download(
            self._node, path, directory=self._directory, style=self._style, max_size=max_size
        ):
            yield piece

    async def write(self, path: str, data: bytes | AsyncIterable[bytes], max_size: int | None) -> dict[str, Any]:
        return await transfer.upload(
            self._node, path, data, directory=self._directory, style=self._style, max_size=max_size
        )


class ScopedFiles:
    def __init__(
        self,
        host: FileHost,
        *,
        style: PathStyle,
        home: str,
        base: str | None = None,
        keep: Iterable[str] = (),
        max_size: int | None = DEFAULT_MAX_SIZE,
    ) -> None:
        self._host = host
        self._style = style
        self._home = home
        self._base = base
        self._keep = list(keep)
        self.max_size = max_size

    def resolve(self, path: str) -> str:
        style = self._style
        if self._base is None and not (style.is_absolute(path) or style.starts_at_home(path)):
            raise ValueError(f"Path must be absolute or start with ~: {path}")
        return style.absolute(path, self._home, self._base)

    async def stat(self, path: str = ".") -> FileInfo:
        return FileInfo.from_dict(await self._host.op("stat", path=self.resolve(path)))

    async def exists(self, path: str) -> bool:
        try:
            await self.stat(path)
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            return False
        return True

    async def read(self, path: str, max_size: int | None = None) -> AsyncIterator[bytes]:
        limit = max_size if max_size is not None else self.max_size
        async for piece in self._host.read(self.resolve(path), limit):
            yield piece

    async def read_file(self, path: str, max_size: int | None = None) -> bytes:
        data = bytearray()
        async for piece in self.read(path, max_size):
            data += piece

        return bytes(data)

    async def list(self, path: str = ".") -> builtins.list[FileInfo]:
        return [FileInfo.from_dict(item) for item in await self._host.op("list", path=self.resolve(path))]

    async def write(self, path: str, data: bytes | AsyncIterable[bytes]) -> FileInfo:
        return FileInfo.from_dict(await self._host.write(self.resolve(path), data, self.max_size))

    async def make_dir(self, path: str) -> None:
        await self._host.op("make_dir", path=self.resolve(path))

    async def delete_file(self, path: str) -> None:
        await self._host.op(
            "delete",
            path=self.resolve(path),
            directory=False,
            recursive=False,
            keep=self._keep,
        )

    async def delete_dir(self, path: str, *, recursive: bool = False) -> None:
        await self._host.op(
            "delete",
            path=self.resolve(path),
            directory=True,
            recursive=recursive,
            keep=self._keep,
        )

    async def copy(self, source: str, target: str) -> None:
        await self._host.op("copy", source=self.resolve(source), target=self.resolve(target))

    async def move(self, source: str, target: str) -> None:
        await self._host.op(
            "move",
            source=self.resolve(source),
            target=self.resolve(target),
            keep=self._keep,
        )

    async def list_readable(self, path: str) -> builtins.list[tuple[str, str]]:
        return [(relative, real) for relative, real in await self._host.op("readable", path=self.resolve(path))]


class LazyFiles:
    def __init__(self, get: Callable[[], Awaitable[ScopedFiles]]) -> None:
        self._get = get

    async def stat(self, path: str = ".") -> FileInfo:
        return await (await self._get()).stat(path)

    async def exists(self, path: str) -> bool:
        return await (await self._get()).exists(path)

    async def read(self, path: str, max_size: int | None = None) -> AsyncIterator[bytes]:
        async for piece in (await self._get()).read(path, max_size):
            yield piece

    async def read_file(self, path: str, max_size: int | None = None) -> bytes:
        return await (await self._get()).read_file(path, max_size)

    async def list(self, path: str = ".") -> builtins.list[FileInfo]:
        return await (await self._get()).list(path)

    async def write(self, path: str, data: bytes | AsyncIterable[bytes]) -> FileInfo:
        return await (await self._get()).write(path, data)

    async def make_dir(self, path: str) -> None:
        await (await self._get()).make_dir(path)

    async def delete_file(self, path: str) -> None:
        await (await self._get()).delete_file(path)

    async def delete_dir(self, path: str, *, recursive: bool = False) -> None:
        await (await self._get()).delete_dir(path, recursive=recursive)

    async def copy(self, source: str, target: str) -> None:
        await (await self._get()).copy(source, target)

    async def move(self, source: str, target: str) -> None:
        await (await self._get()).move(source, target)

    async def list_readable(self, path: str) -> builtins.list[tuple[str, str]]:
        return await (await self._get()).list_readable(path)
