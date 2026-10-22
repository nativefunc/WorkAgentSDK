from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING, Any

from work_agent_sdk.core.errors import ConfigError, SessionClosed
from work_agent_sdk.core.events import (
    Event,
    MessageCompleted,
    MessageStarted,
    MessageUpdated,
    QueueChanged,
    TurnEnded,
)
from work_agent_sdk.core.hooks import Hooks
from work_agent_sdk.core.messages import (
    CustomMessage,
    Message,
    TextPart,
    ToolResultMessage,
)
from work_agent_sdk.core.requests import PendingRequest
from work_agent_sdk.core.results import SessionRecord, TurnResult
from work_agent_sdk.core.service import UNSET, SessionRef, is_unset
from work_agent_sdk.core.tool import unwrap
from work_agent_sdk.runtime.worker.queue import NextSegment, next_segment
from work_agent_sdk.runtime.worker.requests import Requests
from work_agent_sdk.runtime.worker.resources import Resources
from work_agent_sdk.runtime.worker.state import SessionState, build_state

if TYPE_CHECKING:
    from work_agent_sdk.core.agent import Agent
    from work_agent_sdk.runtime.lifecycle import Lifecycle
    from work_agent_sdk.runtime.sessions import Sessions
    from work_agent_sdk.runtime.turn.segment import Segment
    from work_agent_sdk.store import QueueItem

logger = logging.getLogger("work_agent_sdk")


class SessionWorker:
    def __init__(self, sessions: Sessions, record: SessionRecord) -> None:
        self.sessions = sessions
        self.core = sessions.core
        self.record = record
        self.session_id = record.id
        self.queue_lock = asyncio.Lock()
        self._write = asyncio.Lock()
        self._state: SessionState | None = None
        self._loop_task: asyncio.Task | None = None
        self._wakeup = asyncio.Event()
        self.segment: Segment | None = None
        self.segment_task: asyncio.Task | None = None
        self.resources = Resources(self)
        self.requests = Requests(self)

        # 正在流式输出的回答（供 snapshot 使用）：消息 id -> ModelCall
        self.live: dict[str, Any] = {}
        self._live_changes: dict[str, dict[str, Any]] = {}

        # 等待该段结果的句柄：键为 "item:<队列项>" 或 "turn:<turn_id>"
        self._waiters: dict[str, list[asyncio.Future]] = {}
        self.item_turn: dict[str, str] = {}
        self._held = 0
        self.closing = False
        self.shutting_down = False

    def __repr__(self) -> str:
        return f"SessionWorker({self.session_id!r})"

    @property
    def lifecycle(self) -> Lifecycle:
        return self.sessions.lifecycle

    @property
    def agent(self) -> Agent:
        return self.core.agent(self.record.agent)

    @property
    def model(self) -> Any:
        model_id = self.record.config.model
        return self.core.model(model_id) if model_id else self.agent.model

    @property
    def hooks(self) -> list[Hooks]:
        agent = self.agent
        hooks = list(agent.hooks)
        for toolset in agent.toolsets:
            hooks.extend(getattr(unwrap(toolset), "hooks", []) or [])

        return hooks + list(self.core.hooks)

    @property
    def open(self) -> bool:
        return self.record.status == "open" and not self.closing

    async def session_ref(self) -> SessionRef:
        config = self.record.config
        return SessionRef(
            id=self.record.id,
            root_id=self.record.root_id,
            parent_id=self.record.parent_id,
            agent=self.record.agent,
            resources=dict(config.resources),
            metadata=dict(config.metadata),
            task_mode=config.task.mode if config.task else None,
            toolsets=tuple(self.agent.toolsets),
        )

    async def save_record(self) -> None:
        await self.core.store.update_session(self.record)

    async def state(self) -> SessionState:
        if self._state is not None:
            return self._state

        async with self._write:
            if self._state is not None:
                return self._state

            state = build_state(await self.core.store.events(self.session_id))

            # 已关闭的会话不再缓存状态：之后的读取直接从存储重建，不会与其他实例的缓存不一致
            if self.record.status != "closed":
                self._state = state

            return state

    async def append(self, event: Event) -> Event:
        event.session_id = self.session_id
        if event.persisted:
            if self.record.status != "closed":
                await self.state()
            async with self._write:
                event.seq = await self.core.store.append_event(self.session_id, event)
                if self._state is not None:
                    self._state.apply(event)
            self._drop_live_changes(event)
        elif isinstance(event, MessageUpdated) and event.changes:
            self._live_changes.setdefault(event.message_id, {}).update(event.changes)

        if isinstance(event, MessageCompleted) and isinstance(event.message, ToolResultMessage):
            self.requests.forget_call(event.message.tool_call_id)

        self.core.publish(event)
        return event

    def _drop_live_changes(self, event: Event) -> None:
        # 已保存的值比此前仅推送的值新
        if isinstance(event, MessageCompleted):
            self._live_changes.pop(event.message.id, None)
            return

        live = self._live_changes.get(event.message_id) if isinstance(event, MessageUpdated) else None
        if live is None:
            return

        for key in event.changes:
            live.pop(key, None)
        if not live:
            del self._live_changes[event.message_id]

    async def add_message(self, message: CustomMessage) -> CustomMessage:
        if not isinstance(message, CustomMessage):
            raise ConfigError("只能添加 CustomMessage；用户消息请通过 send() 发送")
        if message.status not in ("completed", "in_progress"):
            raise ConfigError("添加消息时 status 只能为 completed 或 in_progress")

        if message.status == "completed":
            message.completed_at = message.completed_at or time.time()
            await self.append(MessageCompleted(message=message, turn_id=message.turn_id))
        else:
            await self.append(MessageStarted(message=message, turn_id=message.turn_id))

        return message

    async def update_message(
        self, message_id: str, *, data: Any = UNSET, display: Any = UNSET, ephemeral: bool = False
    ) -> None:
        state = await self.state()
        message = state.message(message_id)
        if message is None:
            raise LookupError(f"消息 {message_id} 不存在")

        changes: dict[str, Any] = {}
        if not is_unset(data):
            changes["data"] = data
        if not is_unset(display):
            changes["display"] = display
        if changes:
            await self.append(
                MessageUpdated(message_id=message_id, changes=changes, ephemeral=ephemeral, turn_id=message.turn_id)
            )

    async def complete_message(
        self, message_id: str, *, status: str = "completed", data: Any = UNSET, for_model: Any = UNSET
    ) -> bool:
        if status not in ("completed", "failed", "cancelled", "interrupted"):
            raise ConfigError("status 只能为 completed、failed、cancelled 或 interrupted")

        state = await self.state()
        message = state.message(message_id)
        if not isinstance(message, CustomMessage):
            raise LookupError(f"自定义消息 {message_id} 不存在")
        if message.finished:
            return False

        update: dict[str, Any] = {
            "status": status,
            "completed_at": time.time(),
            **self._live_changes.pop(message_id, {}),
        }
        if not is_unset(data):
            update["data"] = data
        if not is_unset(for_model):
            update["for_model"] = for_model

        await self.append(MessageCompleted(message=message.model_copy(update=update), turn_id=message.turn_id))
        return True

    async def complete_tool_result(
        self,
        message_id: str,
        *,
        status: str,
        content: list[Any] | None = None,
        data: Any = None,
        error: str | None = None,
        error_code: str | None = None,
        loaded_tools: list[str] | None = None,
    ) -> None:
        state = await self.state()
        message = state.message(message_id)
        if not isinstance(message, ToolResultMessage) or message.finished:
            return

        final = message.model_copy(
            update={
                "status": status,
                "content": content or [],
                "data": data,
                "error": error,
                "error_code": error_code,
                "loaded_tools": loaded_tools or [],
                "completed_at": time.time(),
            }
        )
        await self.append(MessageCompleted(message=final, turn_id=message.turn_id))

    def snapshot(self, state: SessionState) -> list[Message]:
        found: list[Message] = []
        for message in state.unfinished_messages():
            if message.id in self.live:
                call = self.live[message.id]
                found.append(message.model_copy(update={"content": call.builder.content()}))
            else:
                found.append(message.model_copy(update=self._live_changes.get(message.id, {})))

        return found

    async def queued_items(self) -> list[QueueItem]:
        return await self.core.store.queued(self.session_id)

    async def publish_queue(self) -> None:
        items = await self.queued_items()
        await self.append(QueueChanged(items=[item.summary() for item in items]))

    async def enqueue(self, item: QueueItem) -> None:
        if not self.open:
            raise SessionClosed(self.session_id)

        await self.core.store.enqueue(item)
        await self.publish_queue()
        self.wake()

    async def dequeue(self, item: QueueItem) -> None:
        await self.core.store.dequeue(item.id)
        await self.publish_queue()

    async def cancel_item(self, item_id: str) -> bool:
        async with self.queue_lock:
            if item_id not in {item.id for item in await self.queued_items()}:
                return False
            await self.core.store.dequeue(item_id)

        self._deliver_result(f"item:{item_id}", TurnResult(status="cancelled"))
        await self.publish_queue()
        return True

    async def set_priority(self, item_id: str, priority: int) -> bool:
        async with self.queue_lock:
            if item_id not in {item.id for item in await self.queued_items()}:
                return False
            await self.core.store.set_priority(item_id, priority)
        await self.publish_queue()
        return True

    def result_future(self, key: str) -> asyncio.Future:
        future = asyncio.get_running_loop().create_future()
        self._waiters.setdefault(key, []).append(future)
        return future

    def _deliver_result(self, key: str, result: TurnResult) -> None:
        for future in self._waiters.pop(key, []):
            if not future.done():
                future.set_result(result)

    def resolve_turn(self, turn_id: str, result: TurnResult) -> None:
        for item_id, item_turn in list(self.item_turn.items()):
            if item_turn == turn_id:
                self._deliver_result(f"item:{item_id}", result)
                if result.final:
                    self.item_turn.pop(item_id, None)
        self._deliver_result(f"turn:{turn_id}", result)

    async def pending_changed(self) -> None:
        for session_id in (await self.sessions.lineage(self.session_id))[1:]:
            ancestor = await self.sessions.worker(session_id)
            state = await ancestor.state()
            if state.turn is not None and state.turn.phase == "parked":
                pending = await ancestor.pending(children=True)
                if pending:
                    ancestor.resolve_turn(
                        state.turn.id, TurnResult(turn_id=state.turn.id, status="waiting", pending=pending)
                    )

    async def answer(
        self, request_id: str, value: Any, *, follow: SessionWorker | None = None, key: str = ""
    ) -> asyncio.Future | None:
        if not self.open:
            raise SessionClosed(self.session_id)

        async with self.queue_lock:
            await self.requests.answer(request_id, value)
            future = follow.result_future(key) if follow is not None else None

        self.wake()
        return future

    async def settle(self, task_id: str, result: Any) -> None:
        from work_agent_sdk.core.events import TaskSettled

        state = await self.state()
        wait = state.tasks.get(task_id)
        if wait is None or wait.settled:
            return

        await self.append(TaskSettled(task_id=task_id, result=result, turn_id=wait.turn_id))
        self.wake()

    async def pending(self, *, children: bool = True) -> list[PendingRequest]:
        if self.record.status == "closed":
            return []

        state = await self.state()
        found = [request.to_pending(self.session_id) for request in state.pending_requests()]
        if children:
            for child_id in await self.sessions.descendants(self.session_id):
                child = await self.sessions.worker(child_id)
                found.extend(await child.pending(children=False))

        return found

    def wake(self) -> None:
        if self.shutting_down:
            return
        self._wakeup.set()
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.get_running_loop().create_task(
                self._loop(), name=f"work_agent_sdk:{self.session_id}"
            )

    async def _loop(self) -> None:
        while not self.shutting_down:
            self._wakeup.clear()
            work: NextSegment | None = None
            try:
                async with self.queue_lock:
                    if self.segment is None and self.open and not self._held:
                        work = await next_segment(self)
                        if work is not None:
                            self._start(work)
            except Exception as error:
                logger.exception("会话 %s 确定下一项工作时失败", self.session_id)
                self._fail_waiters(error)
                return

            if work is None:
                if self._wakeup.is_set():
                    continue
                return

            task = self.segment_task
            if task is not None:
                await asyncio.wait([task])
                if not task.cancelled() and task.result() is False:
                    return

    def _start(self, work: NextSegment) -> None:
        from work_agent_sdk.runtime.turn.segment import Segment

        segment = Segment(self, work.turn_id, work.phase, work.items)

        for item in work.items:
            self.item_turn[item.id] = work.turn_id

        self.segment = segment
        self.segment_task = asyncio.get_running_loop().create_task(
            self._run(segment), name=f"work_agent_sdk:{work.turn_id}"
        )

    async def _run(self, segment: Segment) -> bool:
        # 意外错误（几乎都是写存储失败）时本轮在记录中仍是运行状态，与进程中途退出相同：不重试，下次唤醒时按恢复流程继续
        try:
            result = await segment.run()
        except asyncio.CancelledError:
            return True  # 关闭：不写入记录，下次启动时恢复
        except Exception as error:
            logger.exception("会话 %s 的段执行出错，等待下次唤醒时恢复", self.session_id)
            self._fail_waiters(error)
            return False
        finally:
            self.segment = None

        if result.status == "waiting":
            # 交出结果时的待答复请求：段结束前已被答复的请求不再列出
            result = result.model_copy(update={"pending": await self.pending(children=True)})

        # 处于等待状态但没有待答复的请求（仅在等待前台子会话）时，句柄继续等待本轮的下一段
        if result.final or result.pending:
            self.resolve_turn(segment.turn_id, result)
        if result.status == "waiting" and result.pending and self.record.parent_id is not None:
            # 子会话停稳后才告知上级，与顶层会话的请求时机一致
            await self.pending_changed()

        self.wake()
        return True

    def _fail_waiters(self, error: Exception) -> None:
        waiters, self._waiters = self._waiters, {}
        for future in (future for futures in waiters.values() for future in futures):
            if not future.done():
                future.set_exception(error)
                # 只调用了 queued() 的调用方不会读取该异常；错误已记录日志，避免再报"异常未被读取"
                future.add_done_callback(lambda done: done.exception())

    @contextlib.asynccontextmanager
    async def hold_segments(self) -> Any:
        async with self.queue_lock:
            self._held += 1
        try:
            yield
        finally:
            self._held -= 1
            self.wake()

    async def end_waits(self, turn_id: str, request_status: str) -> None:
        import work_agent_sdk.strings.runtime as strings

        state = await self.state()
        for request in [item for item in state.pending_requests() if item.turn_id == turn_id]:
            await self.requests.close(request, request_status)

        for wait in state.open_tasks(turn_id):
            try:
                child = await self.sessions.worker(wait.task_id)
            except KeyError:
                continue  # 子会话已删除
            await child.close(outcome="cancelled")

        state = await self.state()
        reason = strings.REASON_UNANSWERED if request_status == "unanswered" else strings.REASON_STOPPED
        text = strings.NOT_COMPLETED.format(reason=reason)
        for call in state.waiting_calls(turn_id):
            result = state.result_of(call)
            if result is not None:
                await self.complete_tool_result(
                    result.id, status="cancelled", content=[TextPart(text=text)], error=text, error_code=request_status
                )

    async def end_parked(self, status: str) -> TurnResult | None:
        state = await self.state()
        turn = state.turn
        if turn is None or turn.phase != "parked":
            return None

        await self.end_waits(turn.id, "unanswered" if status == "cancelled" else "cancelled")
        result = TurnResult(turn_id=turn.id, status=status)
        await self.append(TurnEnded(result=result, turn_id=turn.id))
        await self.lifecycle.notify("turn_ended", await self.session_ref(), result)
        self.resolve_turn(turn.id, result)
        return result

    async def waiting_on_user(self, turn_id: str) -> bool:
        state = await self.state()
        calls = state.waiting_calls(turn_id)
        if not calls:
            return False

        for call in calls:
            if any(request.pending for request in call.requests):
                continue

            open_tasks = [wait for wait in call.tasks if not wait.settled]
            if not open_tasks:
                return False

            for wait in open_tasks:
                child = await self.sessions.worker(wait.task_id)
                if child.segment is not None:
                    return False

                child_state = await child.state()
                if child_state.turn is None or child_state.turn.phase != "parked":
                    return False
                if not await child.waiting_on_user(child_state.turn.id):
                    return False

        return True

    async def stop(self, *, everything: bool = False) -> None:
        async with self.queue_lock:
            self._held += 1
            task = self.segment_task if self.segment is not None else None
            if task is not None and not task.done():
                task.cancel()

        try:
            if task is not None:
                await asyncio.wait([task])

            await self.end_parked("stopped")
            await self.lifecycle.notify("session_stopped", await self.session_ref(), everything)

            if everything:
                for child_id in await self.sessions.children(self.session_id):
                    child = await self.sessions.worker(child_id)
                    if child.open:
                        await child.stop(everything=True)
        finally:
            self._held -= 1
            self.wake()

    async def close(self, *, outcome: str = "closed") -> None:
        if self.record.status == "closed" or self.closing:
            return

        self.closing = True
        try:
            for child_id in await self.sessions.children(self.session_id):
                child = await self.sessions.worker(child_id)
                await child.close(outcome="cancelled")

            await self.stop(everything=True)
            await self.resources.release()
            await self.lifecycle.notify("session_closing", await self.session_ref())

            for item in await self.core.store.clear_queue(self.session_id):
                self._deliver_result(f"item:{item.id}", TurnResult(status="cancelled"))

            await self.publish_queue()
            self.record.status = "closed"
            self.record.outcome = outcome
            await self.save_record()
            from work_agent_sdk.core.events import SessionEnded

            await self.append(SessionEnded(outcome=outcome))
            self.resources.forget()
            self.requests.forget_all()
            self._state = None
            self._live_changes.clear()
            self.sessions.release(self)
        finally:
            self.closing = False

    async def shutdown(self) -> None:
        self.shutting_down = True
        segment, task = self.segment, self.segment_task
        if segment is not None and task is not None and not task.done():
            segment.shutdown = True
            task.cancel()
            await asyncio.wait([task])

        if self._loop_task is not None and not self._loop_task.done():
            self._loop_task.cancel()
            await asyncio.wait([self._loop_task])
