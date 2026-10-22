from __future__ import annotations

import contextlib
import errno
import hashlib
import uuid
from collections.abc import AsyncIterable, AsyncIterator
from typing import TYPE_CHECKING, Any

from work_agent_sdk.host.files.helper import BLOCK_SIZE, TRANSFER_PREFIX
from work_agent_sdk.host.files.paths import PathStyle

if TYPE_CHECKING:
    from work_agent_sdk.nodes.base import Node

# workspace.files 等开发者文件接口默认的单个文件大小上限
DEFAULT_MAX_SIZE = 100 * 1024 * 1024


def transfer_file(style: PathStyle, directory: str) -> str:
    return style.join(directory, TRANSFER_PREFIX + uuid.uuid4().hex)


async def blocks(data: bytes | AsyncIterable[bytes], max_size: int | None = None) -> AsyncIterator[bytes]:
    total = 0

    def counted(piece: bytes) -> bytes:
        nonlocal total
        total += len(piece)
        if max_size is not None and total > max_size:
            raise ValueError(f"写入的内容超过上限 {max_size} 字节")
        return piece

    if isinstance(data, (bytes, bytearray, memoryview)):
        data = bytes(data)
        for start in range(0, len(data), BLOCK_SIZE):
            yield counted(data[start : start + BLOCK_SIZE])
        return

    pending = bytearray()
    async for piece in data:
        pending += piece
        while len(pending) >= BLOCK_SIZE:
            yield counted(bytes(pending[:BLOCK_SIZE]))
            del pending[:BLOCK_SIZE]

    if pending:
        yield counted(bytes(pending))


async def upload(
    node: Node,
    target: str,
    data: bytes | AsyncIterable[bytes],
    *,
    directory: str,
    style: PathStyle,
    executable: bool = False,
    max_size: int | None = None,
) -> dict[str, Any]:
    staging = transfer_file(style, directory)
    digest = hashlib.sha256()
    size = 0
    try:
        async for piece in blocks(data, max_size):
            await node.write_block(staging, size, piece)
            digest.update(piece)
            size += len(piece)

        if size == 0:
            await node.write_block(staging, 0, b"")

        return dict(
            await node.file_op(
                "commit", staging=staging, target=target, size=size, sha256=digest.hexdigest(), executable=executable
            )
        )
    except BaseException:
        with contextlib.suppress(Exception):
            await node.remove(staging)
        raise


async def download(
    node: Node, source: str, *, directory: str, style: PathStyle, max_size: int | None = None
) -> AsyncIterator[bytes]:
    staging = transfer_file(style, directory)
    try:
        expected = await node.file_op("snapshot", source=source, staging=staging, max_size=max_size)
        size = int(expected["size"])
        digest = hashlib.sha256()
        offset = 0
        while offset < size:
            piece = await node.read_block(staging, offset, min(BLOCK_SIZE, size - offset))
            if not piece:
                break

            digest.update(piece)
            offset += len(piece)
            yield piece

        if offset != size or digest.hexdigest() != expected["sha256"]:
            raise OSError(errno.EIO, f"读取的内容核对不一致：收到 {offset} 字节，应为 {size} 字节", source)
    finally:
        with contextlib.suppress(Exception):
            await node.remove(staging)
