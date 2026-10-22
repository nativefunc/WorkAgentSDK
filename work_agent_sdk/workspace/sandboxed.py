from __future__ import annotations

import errno
import hashlib
import json
import shlex
import struct
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

import work_agent_sdk.nodes.transfer as transfer
from work_agent_sdk.host.commands.process import Stdin
from work_agent_sdk.host.files.helper import FRAME_DATA, FRAME_END
from work_agent_sdk.host.protocol import remote_error

# 执行端在命令的环境变量中给出 Python 与 helper 的位置
HELPER_COMMAND = '"$WORK_AGENT_PYTHON" -I "$WORK_AGENT_FILE_HELPER" '


class SandboxHost:
    def __init__(self, workspace: Any) -> None:
        self._workspace = workspace

    async def _run(
        self, request: dict[str, Any], stdin: Stdin = None, stderr: bytearray | None = None
    ) -> AsyncIterator[bytes]:
        workspace = self._workspace
        command = workspace.command(HELPER_COMMAND + shlex.quote(json.dumps(request, ensure_ascii=False)))
        collected = bytearray() if stderr is None else stderr
        exit_code: int | None = None
        async for chunk in workspace.node.exec(command, stdin):
            if chunk.stream == "stdout":
                yield chunk.data
            elif chunk.stream == "stderr":
                collected += chunk.data
            else:
                exit_code = chunk.code

        if exit_code != 0:
            raise _failure(exit_code, collected.decode(errors="replace"))

    async def op(self, name: str, **arguments: Any) -> Any:
        output = bytearray()
        async for piece in self._run({"op": name, **arguments}):
            output += piece
        return json.loads(output) if output else None

    async def read(self, path: str, max_size: int | None) -> AsyncIterator[bytes]:
        stderr = bytearray()
        digest = hashlib.sha256()
        size = 0
        async for piece in self._run({"op": "read", "path": path, "max_size": max_size}, stderr=stderr):
            digest.update(piece)
            size += len(piece)
            yield piece

        expected = _last_json(stderr.decode(errors="replace"))
        if expected is None or size != expected.get("size") or digest.hexdigest() != expected.get("sha256"):
            raise OSError(errno.EIO, f"读取的内容核对不一致：收到 {size} 字节", path)

    async def write(self, path: str, data: bytes | AsyncIterable[bytes], max_size: int | None) -> dict[str, Any]:
        failure: list[BaseException] = []

        async def frames() -> AsyncIterator[bytes]:
            digest = hashlib.sha256()
            size = 0
            try:
                async for piece in transfer.blocks(data, max_size):
                    digest.update(piece)
                    size += len(piece)
                    yield FRAME_DATA + struct.pack(">I", len(piece)) + piece
            except Exception as error:
                # 不发送结束帧：helper 收不到结束帧即放弃写入；此处的错误在命令结束后抛出
                failure.append(error)
                return

            yield FRAME_END + struct.pack(">Q32s", size, digest.digest())

        request = {"op": "write", "path": path, "staging_dir": self._workspace.tmp}
        try:
            output = bytearray()
            async for piece in self._run(request, frames()):
                output += piece
        except Exception:
            if failure:
                raise failure[0] from None
            raise

        if failure:
            raise failure[0]
        return dict(json.loads(output))


def _last_json(stderr: str) -> dict[str, Any] | None:
    lines = [line for line in stderr.splitlines() if line.strip()]
    if not lines:
        return None

    try:
        value = json.loads(lines[-1])
    except ValueError:
        return None

    return value if isinstance(value, dict) else None


def _failure(exit_code: int | None, stderr: str) -> Exception:
    info = _last_json(stderr)
    if info is not None and "type" in info:
        return remote_error(info)

    detail = stderr.strip() or "无输出"
    return OSError(f"无法在工作区的沙箱中操作文件（退出码 {exit_code}）：{detail}")
