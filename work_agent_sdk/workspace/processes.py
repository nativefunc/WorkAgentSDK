from __future__ import annotations

import asyncio
import codecs
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import work_agent_sdk.strings.workspace as strings
from work_agent_sdk.core.errors import NodeOffline
from work_agent_sdk.core.messages import CustomMessage
from work_agent_sdk.core.service import RunnerAPI
from work_agent_sdk.core.utils import head_and_tail
from work_agent_sdk.host.commands.run import Command
from work_agent_sdk.nodes.base import Node
from work_agent_sdk.workspace.output_log import OutputLog, decode_utf8_prefix
from work_agent_sdk.workspace.store import MAX_OUTPUT_MB, ProcessRecord, ProcessStore

logger = logging.getLogger("work_agent_sdk")

TAIL_CHARS = 2000
TAIL_BYTES = 64 * 1024
READ_BYTES = 256 * 1024
ProcessStatus = Literal["running", "exited", "killed"]
ENDED = ("exited", "killed")


@dataclass
class OutputPiece:
    text: str
    offset: int


class Process:
    """进程句柄，供开发者代码和工具使用。"""

    def __init__(self, manager: Processes, record: ProcessRecord) -> None:
        self._manager = manager
        self._record = record

    def __repr__(self) -> str:
        return f"Process({self.id!r}, {self.status!r})"

    @property
    def id(self) -> str:
        return self._record.id

    @property
    def session_id(self) -> str:
        return self._record.session_id

    @property
    def key(self) -> str | None:
        """启动时指定的 key；同一 key 只启动一次。"""
        return self._record.key

    @property
    def call_id(self) -> str | None:
        return self._record.call_id

    @property
    def seen_offset(self) -> int:
        return self._record.seen_offset

    @property
    def command(self) -> str:
        return self._record.command

    @property
    def node(self) -> str:
        return self._record.node

    @property
    def path(self) -> str:
        return self._record.path

    @property
    def background(self) -> bool:
        return self._record.background

    @property
    def status(self) -> str:
        return self._record.status

    @property
    def exit_code(self) -> int | None:
        return self._record.exit_code

    @property
    def started_at(self) -> float:
        return self._record.started_at

    @property
    def ended_at(self) -> float | None:
        return self._record.ended_at

    async def refresh(self) -> Process:
        record = await self._manager.load(self.id)
        if record is not None:
            self._record = record
        return self

    async def output(self, after: int = 0, *, follow: bool = True) -> AsyncIterator[OutputPiece]:
        """从指定位置读取输出。follow=True 时持续读取直到进程结束，否则只读取已有输出。"""
        async for piece in self._manager.output(self.id, after, live=follow):
            yield piece

    async def text(self, after: int = 0) -> str:
        """返回从 after 起的已有输出，不等待。"""
        return "".join([piece.text async for piece in self.output(after, follow=False)])

    async def wait_output(self, timeout: float | None) -> tuple[str, bool]:
        """等待进程结束或超时，返回（期间的输出，是否已结束）。"""
        return await self._manager.wait_output(self.id, timeout)

    async def move_to_background(self) -> bool:
        """将未在时限内结束的前台命令转为后台进程；进程已结束时返回 False。"""
        return await self._manager.move_to_background(self.id)

    async def mark_seen(self, *, seen_offset: int) -> None:
        """记录模型已读取的输出位置，shell_input 从该位置继续返回。"""
        await self._manager.mark_seen(self.id, seen_offset=seen_offset)
        await self.refresh()

    async def wait(self) -> int | None:
        await self._manager.wait(self.id)
        await self.refresh()
        return self.exit_code

    async def kill(self) -> None:
        await self._manager.kill(self.id)
        await self.refresh()

    async def write(self, text: str) -> None:
        await self._manager.write(self.id, text)


class _Live:
    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.stdin: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.listeners: list[asyncio.Queue] = []
        self.finished = asyncio.Event()
        self.killing = False

        # 进程已结束且正在写入结束记录时，终止操作不得打断写入，否则记录将一直停留在运行状态
        self.exiting = False
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

        # 输出总字节数，以及其中写入日志文件的字节数（超出上限的部分不写入）
        self.offset = 0
        self.written = 0

        # 最近的输出；超出日志上限后仍可读取末尾部分
        self.tail = bytearray()
        self.tail_start = 0
        self.max_output_bytes = 0
        self.session_id = ""
        self.call_id: str | None = None
        self.message_id: str | None = None
        self.process_info: dict[str, Any] = {}  # 推送输出时附带的进程信息

        # 进程记录的读取、修改和保存均在此锁内完成，避免输出、标记和结束操作相互覆盖
        self.lock = asyncio.Lock()


class Processes:
    def __init__(self, api: RunnerAPI, store: ProcessStore) -> None:
        self.api = api
        self._live: dict[str, _Live] = {}
        self.log = OutputLog(str(api.files("workspace") / "logs"))
        self.store = store

    async def load(self, process_id: str) -> ProcessRecord | None:
        return await self.store.get(process_id)

    async def save(self, record: ProcessRecord) -> None:
        await self.store.put(record)

    async def records(self, *, session_id: str | None = None, status: str | None = None) -> list[ProcessRecord]:
        return await self.store.list(session_id=session_id, status=status)

    @contextlib.asynccontextmanager
    async def _editing(self, process_id: str) -> AsyncIterator[ProcessRecord | None]:
        live = self._live.get(process_id)
        async with live.lock if live is not None else contextlib.nullcontext():
            record = await self.load(process_id)
            yield record
            if record is not None:
                await self.save(record)

    async def start(
        self,
        session_id: str,
        node: Node,
        command: Command,
        *,
        node_name: str,
        path: str,
        background: bool = True,
        key: str | None = None,
        call_id: str | None = None,
        max_output_mb: float = MAX_OUTPUT_MB,
    ) -> Process:
        if key is not None:
            for existing in await self.records(session_id=session_id):
                if existing.key == key:
                    return Process(self, existing)

        record = ProcessRecord(
            session_id=session_id,
            call_id=call_id,
            key=key,
            command=command.line,
            node=node_name,
            path=path,
            background=background,
            max_output_bytes=int(max_output_mb * 1024 * 1024),
        )

        # 先创建临时目录：节点无法连接时在此处报错，不会留下无法启动的进程记录
        await node.make_dir(command.tmp)
        live = self._live[record.id] = _Live()
        live.session_id = session_id
        live.call_id = call_id
        live.max_output_bytes = record.max_output_bytes

        if background:
            record.message_id = await self._add_background_process_message(record)

        await self.save(record)
        live.task = asyncio.create_task(self._run(record.id, node, command), name=f"work_agent_sdk:{record.id}")
        return Process(self, record)

    async def _run(self, process_id: str, node: Node, command: Command) -> None:
        live = self._live[process_id]

        async def stdin() -> AsyncIterator[bytes]:
            while (piece := await live.stdin.get()) is not None:
                yield piece

        exit_code: int | None = None
        detail: str | None = None
        try:
            async for chunk in node.exec(command, stdin()):
                if chunk.stream == "exit":
                    exit_code = chunk.code
                elif chunk.data:
                    await self._on_output(process_id, chunk.data)
        except asyncio.CancelledError:
            if not live.killing:
                # 后端关闭：记录保持运行状态，下次启动时统一标记为已结束
                raise
        except (ConnectionError, NodeOffline, OSError) as error:
            detail = strings.PROCESS_CONNECTION_LOST.format(error=error)
        except Exception as error:
            logger.exception("进程 %s 出错", process_id)
            detail = strings.PROCESS_FAILED.format(error=f"{type(error).__name__}: {error}")

        await self._finish(process_id, exit_code, detail)

    async def _finish(self, process_id: str, exit_code: int | None, detail: str | None) -> None:
        live = self._live[process_id]
        live.exiting = True
        try:
            await self._on_exit(process_id, exit_code, detail)
        finally:
            # 写入记录出错时，也须唤醒等待该进程的调用方
            if not live.finished.is_set():
                live.finished.set()
                for queue in list(live.listeners):
                    queue.put_nowait(None)

    async def get(self, process_id: str) -> Process | None:
        record = await self.load(process_id)
        return Process(self, record) if record is not None else None

    async def list(self, session_ids: list[str]) -> list[Process]:
        wanted = set(session_ids)
        return [Process(self, record) for record in await self.records() if record.session_id in wanted]

    async def _on_output(self, process_id: str, data: bytes) -> None:
        # 热路径，不访问数据库
        live = self._live[process_id]
        async with live.lock:
            text = live.decoder.decode(data)
            if not text:
                return

            encoded = text.encode()
            offset = live.offset
            live.offset += len(encoded)
            room = live.max_output_bytes - live.written
            if room > 0 and live.written == offset:
                # 日志只保存到上限，超出部分仅在内存中保留最近一段
                kept = encoded[:room]
                await self.log.append(process_id, kept)
                live.written += len(kept)

            live.tail += encoded
            if len(live.tail) > TAIL_BYTES:
                cut = len(live.tail) - TAIL_BYTES
                del live.tail[:cut]
                live.tail_start += cut

        # 仅推送给前端，不写入会话记录：后台进程推送到对应消息，前台命令由 Shell 工具推送到本次调用
        if live.message_id is not None:
            with contextlib.suppress(Exception):
                await self.api.update_message(
                    live.session_id,
                    live.message_id,
                    data={**live.process_info, "output": text, "offset": offset},
                    ephemeral=True,
                )

        for queue in list(live.listeners):
            queue.put_nowait(OutputPiece(text, offset))

    async def _on_exit(self, process_id: str, exit_code: int | None, detail: str | None) -> None:
        live = self._live[process_id]
        async with self._editing(process_id) as record:
            if record is None:
                return

            record.exit_code = exit_code
            record.output_offset = live.offset
            record.recorded_bytes = live.written
            record.status = "killed" if live.killing else "exited"
            record.ended_at = time.time()

        await self._complete_background_process_message(record, detail)
        live.finished.set()

        for queue in list(live.listeners):
            queue.put_nowait(None)

        if live.written >= live.offset:
            self._live.pop(process_id, None)

    def _total(self, record: ProcessRecord) -> int:
        # 记录缺失（后端崩溃）时取日志大小
        live = self._live.get(record.id)
        if live is not None:
            return live.offset
        return max(record.output_offset, self.log.size(record.id))

    async def tail(self, process_id: str, chars: int = TAIL_CHARS) -> str:
        record = await self.load(process_id)
        if record is None:
            return ""

        start = max(0, self._total(record) - chars * 4)
        pieces = [piece.text async for piece in self.output(process_id, start, live=False)]
        return head_and_tail("".join(pieces)[-chars:], chars).strip() or strings.PROCESS_NO_OUTPUT

    # workspace.process 消息只属于后台进程：进入后台时添加，结束时完成。前台命令的输出随 shell 调用返回

    def _process_info(self, record: ProcessRecord) -> dict[str, Any]:
        return {
            "process_id": record.id,
            "command": record.command,
            "node": record.node,
            "path": record.path,
            "status": record.status,
            "exit_code": record.exit_code,
            "call_id": record.call_id,
        }

    async def _add_background_process_message(self, record: ProcessRecord) -> str | None:
        try:
            message = await self.api.add_message(
                record.session_id,
                CustomMessage("workspace.process", data=self._process_info(record), status="in_progress"),
            )
        except Exception:
            logger.exception("进程 %s 的消息未能写入对话", record.id)
            return None

        live = self._live.get(record.id)
        if live is not None:
            live.message_id = message.id
            live.process_info = self._process_info(record)

        return message.id

    async def _complete_background_process_message(self, record: ProcessRecord, detail: str | None) -> None:
        if record.message_id is None:
            return

        tail = await self.tail(record.id)
        if detail:
            text = strings.PROCESS_ENDED_WITH_DETAIL.format(
                id=record.id, command=record.command, detail=detail, tail=tail
            )
        elif record.status == "killed":
            text = strings.PROCESS_KILLED.format(id=record.id, command=record.command, tail=tail)
        else:
            text = strings.PROCESS_EXITED.format(
                id=record.id, command=record.command, exit_code=record.exit_code, tail=tail
            )

        try:
            await self.api.complete_message(
                record.session_id,
                record.message_id,
                status="completed" if record.status == "exited" and record.exit_code == 0 else "failed",
                data={**self._process_info(record), "detail": detail},
                for_model=text,
            )
        except LookupError:
            pass  # 会话或消息已删除
        except Exception:
            logger.exception("进程 %s 的结束状态未能写入对话", record.id)

    async def wait_output(self, process_id: str, timeout: float | None) -> tuple[str, bool]:
        live = self._live.get(process_id)
        if live is None or live.finished.is_set():
            return "", True

        queue: asyncio.Queue = asyncio.Queue()
        live.listeners.append(queue)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout if timeout else None
        pieces: list[str] = []
        finished = False
        try:
            while True:
                remaining = None if deadline is None else deadline - loop.time()
                if remaining is not None and remaining <= 0:
                    break

                try:
                    piece = await asyncio.wait_for(queue.get(), timeout=remaining)
                except TimeoutError:
                    break

                if piece is None:
                    finished = True
                    break

                pieces.append(piece.text)
        finally:
            with contextlib.suppress(ValueError):
                live.listeners.remove(queue)

        return "".join(pieces), finished

    async def mark_seen(self, process_id: str, **fields: Any) -> None:
        async with self._editing(process_id) as record:
            if record is not None:
                for name, value in fields.items():
                    setattr(record, name, value)

    async def move_to_background(self, process_id: str) -> bool:
        async with self._editing(process_id) as record:
            if record is None or record.status in ENDED:
                return False

            record.background = True
            record.message_id = await self._add_background_process_message(record)

        return True

    async def wait(self, process_id: str) -> None:
        live = self._live.get(process_id)
        if live is not None:
            await live.finished.wait()

    async def output(self, process_id: str, after: int = 0, *, live: bool = True) -> AsyncIterator[OutputPiece]:
        record = await self.load(process_id)
        if record is None:
            return

        state = self._live.get(process_id)
        queue: asyncio.Queue | None = None
        if live and state is not None and not state.finished.is_set():
            queue = asyncio.Queue()
            state.listeners.append(queue)

        try:
            position = after

            # 先确定本次从日志读取的终点，之后的新输出由队列衔接
            logged = state.written if state is not None else self.log.size(process_id)
            while position < logged:
                end = min(logged, position + READ_BYTES)
                data = await self.log.read(process_id, position, end)
                if not data:
                    break

                # 分块读取可能截断多字节字符：只返回完整字符，剩余字节并入下一块
                text, used = decode_utf8_prefix(data, final=position + len(data) >= logged)
                if not used:
                    break

                yield OutputPiece(text, position)
                position += used

            total = state.offset if state is not None else self._total(record)
            if position < total:
                tail_start = state.tail_start if state is not None else total
                if position < tail_start:
                    yield OutputPiece(strings.PROCESS_OUTPUT_GAP.format(size=tail_start - position), position)
                    position = tail_start
                if state is not None:
                    data = bytes(state.tail[position - state.tail_start : total - state.tail_start])
                    yield OutputPiece(data.decode(errors="replace"), position)
                    position = total

            if queue is None:
                return

            while (piece := await queue.get()) is not None:
                if piece.offset >= position:
                    yield piece
        finally:
            if queue is not None and state is not None:
                with contextlib.suppress(ValueError):
                    state.listeners.remove(queue)

    async def kill(self, process_id: str) -> None:
        live = self._live.get(process_id)
        if live is None or live.finished.is_set() or live.task is None:
            return

        if not live.exiting:
            live.killing = True
            live.task.cancel()

        await asyncio.gather(live.task, return_exceptions=True)

        if not live.finished.is_set() and not live.exiting:
            # 任务在开始执行前被取消，_run 未运行，在此补写结束记录
            await self._finish(process_id, None, None)

        await live.finished.wait()

    async def write(self, process_id: str, text: str) -> None:
        live = self._live.get(process_id)
        if live is None or live.finished.is_set():
            raise LookupError(f"进程 {process_id} 已结束，无法写入输入")
        live.stdin.put_nowait(text.encode())

    async def kill_call(self, session_id: str, call_id: str) -> None:
        for record in await self.records(session_id=session_id):
            if record.call_id == call_id and not record.background and record.status not in ENDED:
                await self.kill(record.id)

    async def kill_session(self, session_id: str, *, background_only: bool = False) -> None:
        for record in await self.records(session_id=session_id):
            if record.status in ENDED or (background_only and not record.background):
                continue
            await self.kill(record.id)

    async def end_leftovers(self) -> None:
        for record in await self.records(status="running"):
            record.status = "exited"
            record.ended_at = time.time()
            await self.save(record)
            await self._complete_background_process_message(record, strings.PROCESS_BACKEND_RESTARTED)

    async def delete_session(self, session_id: str) -> None:
        for process in await self.records(session_id=session_id):
            await self.log.remove(process.id)
            await self.store.delete(process.id)

    async def close(self) -> None:
        tasks = [live.task for live in self._live.values() if live.task is not None and not live.task.done()]
        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self._live.clear()
