from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import signal
import sys
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING, Any

import work_agent_sdk.host.protocol as protocol
from work_agent_sdk.host.commands.env import inherited_variables
from work_agent_sdk.host.commands.run import Command, run_command
from work_agent_sdk.host.window import SendWindow

if TYPE_CHECKING:
    from work_agent_sdk.device.policy import DevicePolicy

MAX_LOGGED_LINE = 4000
GRACE_MARGIN = 30
# 每条命令每个方向最多留存的未确认数据；写满后暂停产生，重连后继续
WINDOW = 4 * 1024 * 1024
# 设备收到输入后，每累积这么多字节向后端回执一次（使后端能释放其输入缓存并继续发送）
STDIN_ACK_INTERVAL = 256 * 1024


def elapsed_seconds(started: float) -> float:
    return round(time.monotonic() - started, 3)


def encode_output(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _proc_start_token(pid: int) -> int | None:
    # 进程组号可能被重用，清理前用启动时刻核对身份；取不到时返回 None，宁可漏清也不误杀
    if sys.platform.startswith("linux"):
        try:
            with open(f"/proc/{pid}/stat", "rb") as file:
                data = file.read()
            fields = data[data.rindex(b")") + 2 :].split()
            return int(fields[19])
        except (OSError, ValueError, IndexError):
            return None

    if sys.platform == "darwin":
        return _darwin_start_token(pid)
    return None


def _darwin_start_token(pid: int) -> int | None:
    # struct proc_bsdinfo 长 136 字节，末尾为 pbi_start_tvsec、pbi_start_tvusec（XNU bsd/sys/proc_info.h）
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        libc.proc_pidinfo.restype = ctypes.c_int
        libc.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        proc_pidt_bsdinfo = 3  # PROC_PIDTBSDINFO
        struct_size = 136
        buffer = ctypes.create_string_buffer(struct_size)
        written = libc.proc_pidinfo(pid, proc_pidt_bsdinfo, 0, buffer, struct_size)
        if written < struct_size:
            return None

        raw = buffer.raw
        tvsec = int.from_bytes(raw[120:128], "little")
        tvusec = int.from_bytes(raw[128:136], "little")
        return tvsec * 1_000_000 + tvusec
    except Exception:
        return None


class CommandProcesses:
    # 守护进程重启后上一轮的命令会成为孤儿，启动时按登记逐一终止

    def __init__(self, directory: str) -> None:
        self.directory = directory

    def _path(self, command_id: str) -> str:
        return os.path.join(self.directory, command_id)

    def record(self, command_id: str, pid: int) -> None:
        with contextlib.suppress(OSError):
            os.makedirs(self.directory, exist_ok=True)
            token = _proc_start_token(pid)
            with open(self._path(command_id), "w") as file:
                file.write(f"{pid}\n{token if token is not None else ''}")

    def forget(self, command_id: str) -> None:
        with contextlib.suppress(OSError):
            os.unlink(self._path(command_id))

    def kill_leftovers(self) -> None:
        try:
            names = os.listdir(self.directory)
        except OSError:
            return

        for name in names:
            try:
                pid_text, _, token_text = open(self._path(name)).read().partition("\n")
                pid = int(pid_text)
            except (OSError, ValueError):
                self.forget(name)
                continue

            recorded = int(token_text) if token_text.strip() else None
            current = _proc_start_token(pid)

            if recorded is not None and current == recorded:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(pid, signal.SIGKILL)

            self.forget(name)


class RunningCommand:
    def __init__(self, command_id: str, has_stdin: bool) -> None:
        self.id = command_id
        self.task: asyncio.Task | None = None
        self.stdin: asyncio.Queue[bytes | None] | None = asyncio.Queue() if has_stdin else None
        self.out = SendWindow(WINDOW)
        self.stdin_received = 0  # 已收到并入队的输入字节数（用于去重和重连上报）
        self.stdin_consumed = 0  # 命令已读取的输入字节数（据此向后端回执，使输入窗口对未被读取的输入施加背压）
        self.stdin_acked = 0  # 已向后端回执的输入位置
        self.stdin_total: int | None = None  # 后端告知的输入总字节数（收到 stdin_close 后）
        self.exit_code: int | None = None
        self.finished = False

        # 后端是否正在当前连接上跟踪该命令；重连补发完成前为 False，其间新输出只留存不发送
        self.attached = True

    @property
    def offset(self) -> int:
        return self.out.produced

    def accept_input(self, offset: int, data: bytes) -> bytes:
        end = offset + len(data)
        if end <= self.stdin_received or offset > self.stdin_received:
            return b""

        piece = data[self.stdin_received - offset :]
        self.stdin_received = end
        return piece


class DeviceCommands:
    def __init__(
        self,
        *,
        policy: DevicePolicy | None,
        env: list[str],
        enabled: bool,
        grace: Callable[[], float],
        post: Callable[[dict[str, Any]], Awaitable[bool]],
        spawn: Callable[[Coroutine[Any, Any, Any]], None],
        audit: Callable[..., None],
    ) -> None:
        self.policy = policy
        self.env = env
        self.enabled = enabled
        self._grace = grace
        self._post = post
        self._spawn = spawn
        self._audit = audit
        self._commands: dict[str, RunningCommand] = {}
        self._expiry: asyncio.TimerHandle | None = None

        self._processes: CommandProcesses | None = None
        if policy is not None:
            self._processes = CommandProcesses(os.path.join(policy.data_dir, "commands"))
            self._processes.kill_leftovers()

    def positions(self) -> dict[str, int]:
        return {command_id: running.stdin_received for command_id, running in self._commands.items()}

    def start(self, message: protocol.CommandStart) -> None:
        if message.id in self._commands:
            raise ValueError(f"命令编号 {message.id} 重复")
        if not self.enabled:
            self._spawn(self._reject(message.id))
            return

        running = RunningCommand(message.id, message.stdin)
        self._commands[message.id] = running
        running.task = asyncio.create_task(self._run(running, message.command))

    def stdin(self, message: protocol.StdinData) -> None:
        running = self._commands.get(message.id)
        if running is None or running.stdin is None:
            return

        piece = running.accept_input(message.offset, base64.b64decode(message.data))
        if piece:
            running.stdin.put_nowait(piece)

        # 按命令已读取的位置回执而不是收到即回执：命令不读输入时后端的窗口会写满并暂停
        self._close_stdin_if_complete(running)

    def stdin_close(self, message: protocol.StdinClose) -> None:
        running = self._commands.get(message.id)
        if running is None or running.stdin is None:
            return

        running.stdin_total = message.total
        self._close_stdin_if_complete(running)

    def acknowledge(self, message: protocol.Ack) -> None:
        running = self._commands.get(message.id)
        if running is not None:
            running.out.ack(message.received)

    def cancel(self, message: protocol.Cancel) -> None:
        self._drop(message.id)

    def connected(self) -> None:
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None

    def disconnected(self) -> None:
        for running in self._commands.values():
            running.attached = False

        if self._commands:
            self._expiry = asyncio.get_running_loop().call_later(self._grace() + GRACE_MARGIN, self._end_all)

    async def resume(self, resume: dict[str, int]) -> None:
        for command_id in list(self._commands):
            if command_id not in resume:
                self._drop(command_id)

        for command_id, received in resume.items():
            running = self._commands.get(command_id)
            if running is None:
                await self._post_output(
                    command_id, "stderr", received, "\n[设备守护进程已重启，命令已终止，结果未知]\n".encode()
                )
                await self._post({"type": "exit", "id": command_id, "code": None})
                continue

            running.out.ack(received)

            # 补发期间命令可能仍在产出：反复取快照直到追平，再置 attached。
            # 追平与置位之间没有 await，因此不会有输出既不在补发范围内、又未被实时发送
            position = received
            while position < running.out.produced:
                for offset, data, stream in running.out.items_from(position):
                    await self._post_output(command_id, stream, offset, data)
                    position = offset + len(data)

            running.attached = True
            if running.finished:
                await self._post(_exit_message(running))
                self._forget_later(command_id)

    async def _reject(self, command_id: str) -> None:
        text = "该设备仅开放文件读写，不允许执行命令；设备守护进程需以 --sandbox 启动\n"
        await self._post_output(command_id, "stderr", 0, text.encode())
        await self._post({"type": "exit", "id": command_id, "code": 126})

    async def _post_output(self, command_id: str, stream: str, offset: int, data: bytes) -> None:
        await self._post(
            {"type": "output", "id": command_id, "stream": stream, "offset": offset, "data": encode_output(data)}
        )

    @staticmethod
    def _close_stdin_if_complete(running: RunningCommand) -> None:
        # 缺口由后端重发补齐，收齐之前不送 EOF
        total = running.stdin_total
        if running.stdin is not None and total is not None and running.stdin_received >= total:
            running.stdin.put_nowait(None)

    async def _run(self, running: RunningCommand, message: dict[str, Any]) -> None:
        async def stdin_chunks():
            while (piece := await running.stdin.get()) is not None:
                yield piece
                running.stdin_consumed += len(piece)
                if running.stdin_consumed - running.stdin_acked >= STDIN_ACK_INTERVAL:
                    running.stdin_acked = running.stdin_consumed
                    self._spawn(self._post({"type": "stdin_ack", "id": running.id, "received": running.stdin_consumed}))

        exit_code: int | None = 127
        started = time.monotonic()
        line = str(message.get("line") or "")
        self._audit(
            "command",
            id=running.id,
            line=line[:MAX_LOGGED_LINE],
            line_length=len(line) if len(line) > MAX_LOGGED_LINE else None,
            cwd=message.get("cwd"),
            unsandboxed=bool(message.get("unsandboxed")) or None,
            # 环境变量的值可能是密钥，只记名称
            env=sorted(message.get("env") or {}) or None,
        )

        try:
            if not self.enabled or self.policy is None:
                raise PermissionError("该设备仅开放文件读写，不允许执行命令；设备守护进程需以 --sandbox 启动")

            processes = self._processes
            chunks = run_command(
                Command.model_validate(message),
                stdin_chunks() if running.stdin is not None else None,
                variables=inherited_variables(self.env),
                restrict=self.policy.restrict,
                on_start=lambda pid: processes.record(running.id, pid) if processes else None,
            )
            async for chunk in chunks:
                if chunk.stream == "exit":
                    exit_code = chunk.code
                else:
                    await self._emit(running, chunk.stream, chunk.data)
        except asyncio.CancelledError:
            self._audit("command_exit", id=running.id, cancelled=True, seconds=elapsed_seconds(started))
            raise
        except Exception as error:
            self._audit("command_error", id=running.id, error=str(error))
            await self._emit(running, "stderr", f"{error}\n".encode())

        running.exit_code = exit_code
        running.finished = True
        if self._processes is not None:
            self._processes.forget(running.id)

        self._audit("command_exit", id=running.id, exit_code=exit_code, seconds=elapsed_seconds(started))

        if running.attached:
            await self._post(_exit_message(running))

        self._forget_later(running.id)

    async def _emit(self, running: RunningCommand, stream: str, data: bytes) -> None:
        # 窗口写满时先等后端确认，命令随之暂停
        await running.out.wait_room()
        offset = running.out.add(data, stream)
        if running.attached:
            await self._post_output(running.id, stream, offset, data)

    def _forget_later(self, command_id: str) -> None:
        # 发送退出码时连接恰好断开的话，重连后还要能补发
        asyncio.get_running_loop().call_later(self._grace() + GRACE_MARGIN, self._drop, command_id)

    def _end_all(self) -> None:
        self._expiry = None
        for command_id in list(self._commands):
            self._drop(command_id)

    def _drop(self, command_id: str) -> None:
        running = self._commands.pop(command_id, None)
        if running is None:
            return

        if running.task is not None and not running.task.done():
            running.task.cancel()
        if self._processes is not None:
            self._processes.forget(command_id)


def _exit_message(running: RunningCommand) -> dict[str, Any]:
    return {"type": "exit", "id": running.id, "code": running.exit_code, "output": running.out.produced}
