from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
from collections.abc import AsyncIterable, AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Literal

IS_WINDOWS = sys.platform == "win32"
READ_SIZE = 65536
KILL_AFTER = 5
# 队列有上限：消费方停止读取时读取任务阻塞，命令写满管道后自行暂停，输出不在内存中无限堆积
OUTPUT_QUEUE_LIMIT = 32
# Windows 上不分配控制台：框架启动的浏览器不依附于设备守护进程的控制台窗口
DETACHED_PROCESS = 0x00000008

Stdin = bytes | AsyncIterable[bytes] | None


@dataclass
class OutputChunk:
    stream: Literal["stdout", "stderr", "exit"]
    data: bytes = b""
    code: int | None = None


@dataclass
class RunResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


async def collect_output(chunks: AsyncIterator[OutputChunk]) -> RunResult:
    stdout = bytearray()
    stderr = bytearray()
    exit_code = -1
    async for chunk in chunks:
        if chunk.stream == "stdout":
            stdout += chunk.data
        elif chunk.stream == "stderr":
            stderr += chunk.data
        elif chunk.code is not None:
            exit_code = chunk.code

    return RunResult(exit_code, stdout.decode(errors="replace"), stderr.decode(errors="replace"))


async def run_process(
    argv: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    stdin: Stdin = None,
    timeout: float | None = None,
    on_start: Callable[[int], None] | None = None,
) -> AsyncIterator[OutputChunk]:
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **own_group(),
    )
    if on_start is not None:
        on_start(process.pid)

    output: asyncio.Queue[OutputChunk | None] = asyncio.Queue(OUTPUT_QUEUE_LIMIT)

    async def forward(stream: asyncio.StreamReader | None, name: Literal["stdout", "stderr"]) -> None:
        if stream is None:
            return
        while data := await stream.read(READ_SIZE):
            await output.put(OutputChunk(name, data))

    async def wait_for_exit() -> None:
        await asyncio.gather(*readers, return_exceptions=True)
        await process.wait()
        await output.put(None)

    writer = asyncio.create_task(_write_stdin(process, stdin)) if stdin is not None else None
    readers = [
        asyncio.create_task(forward(process.stdout, "stdout")),
        asyncio.create_task(forward(process.stderr, "stderr")),
    ]
    exited = asyncio.create_task(wait_for_exit())
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout if timeout else None
    finished = False
    try:
        while True:
            remaining = None if deadline is None else max(0.0, deadline - loop.time())
            try:
                chunk = await asyncio.wait_for(output.get(), timeout=remaining)
            except TimeoutError:
                stop_process_group(process)
                await asyncio.wait([exited], timeout=KILL_AFTER + 1)

                while not output.empty():
                    leftover = output.get_nowait()
                    if leftover is not None:
                        yield leftover

                yield OutputChunk("stderr", f"\n[超时：已在 {timeout:g} 秒后终止]\n".encode())
                yield OutputChunk("exit", code=124)
                finished = True
                return

            if chunk is None:
                break

            yield chunk

        finished = True
        yield OutputChunk("exit", code=process.returncode)
    finally:
        if not finished:
            stop_process_group(process)
        for task in (writer, exited, *readers):
            if task is not None and not task.done():
                task.cancel()


async def _write_stdin(process: asyncio.subprocess.Process, stdin: Stdin) -> None:
    assert process.stdin is not None

    try:
        if isinstance(stdin, (bytes, bytearray)):
            process.stdin.write(stdin)
            await process.stdin.drain()
        elif stdin is not None:
            async for piece in stdin:
                process.stdin.write(piece)
                await process.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        with contextlib.suppress(Exception):
            process.stdin.close()


def own_group(*, detached: bool = False) -> dict[str, Any]:
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | (DETACHED_PROCESS if detached else 0)
        return {"creationflags": flags}
    return {"start_new_session": True}


def spawn_detached(argv: list[str], *, env: dict[str, str], output: Any) -> subprocess.Popen:
    return subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, env=env, **own_group(detached=True)
    )


# 后台运行的 taskkill 任务：保留引用，以免任务被回收
_killing: set[asyncio.Task] = set()


def stop_process_group(process: asyncio.subprocess.Process | subprocess.Popen) -> None:
    if IS_WINDOWS:
        task = asyncio.get_running_loop().create_task(_taskkill(process.pid))
        _killing.add(task)
        task.add_done_callback(_killing.discard)
        return

    _signal_group(process.pid, signal.SIGTERM)
    asyncio.get_running_loop().call_later(KILL_AFTER, _signal_group, process.pid, signal.SIGKILL)


async def _taskkill(pid: int) -> None:
    killer = await asyncio.create_subprocess_exec(
        "taskkill", "/F", "/T", "/PID", str(pid), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    await killer.wait()


def _signal_group(pid: int, signal_number: int) -> None:
    # 进程以 start_new_session 启动，进程组号即其 pid
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal_number)
