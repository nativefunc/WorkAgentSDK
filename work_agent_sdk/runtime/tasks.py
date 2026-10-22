from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from work_agent_sdk.core.agent import Agent
from work_agent_sdk.core.errors import ConfigError, ToolError
from work_agent_sdk.core.events import TaskAwaited
from work_agent_sdk.core.messages import CustomMessage, UserMessage
from work_agent_sdk.core.results import SessionInfo, TaskConfig, TaskResult, TurnResult
from work_agent_sdk.core.service import SessionRef
from work_agent_sdk.runtime.context import CallScope, Suspended, require_scope
from work_agent_sdk.store import QueueItem

if TYPE_CHECKING:
    from work_agent_sdk.runtime.context import RunContext
    from work_agent_sdk.runtime.sessions import Sessions
    from work_agent_sdk.runtime.worker.worker import SessionWorker

logger = logging.getLogger("work_agent_sdk")
FINAL_TO_TASK = {
    "completed": "completed",
    "error": "error",
    "rejected": "rejected",
    "stopped": "stopped",
    "cancelled": "cancelled",
}


def task_result(task_id: str, agent: str, result: TurnResult) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        agent=agent,
        status=FINAL_TO_TASK.get(result.status, "error"),
        text=result.text,
        data=result.data,
        error=result.error,
    )


class TaskTree:
    def __init__(self, sessions: Sessions) -> None:
        self.sessions = sessions

    def agent_name(self, agent: Agent | str) -> str:
        name = agent.name if isinstance(agent, Agent) else agent
        registered = self.sessions.core.agent(name)
        if isinstance(agent, Agent) and registered is not agent:
            raise ConfigError(f"Agent {name} 与 Runner 上登记的不是同一对象；请使用登记时的 Agent 实例")
        return name

    async def spawn(
        self,
        parent: SessionWorker,
        agent: Agent | str,
        *,
        mode: str,
        tools: list[str] | None = None,
        parent_call_id: str | None = None,
    ) -> SessionWorker:
        if parent.record.parent_id is not None:
            raise ConfigError("子会话不能再创建子会话")
        if not parent.open:
            raise ConfigError(f"会话 {parent.session_id} 已关闭")

        name = self.agent_name(agent)
        config = parent.record.config.model_copy(deep=True)
        config.task = TaskConfig(mode=mode, tools=tools)
        config.forked_from = None
        config.model = None
        config.thinking = None
        return await self.sessions.create(
            name, config, parent_id=parent.session_id, parent_call_id=parent_call_id, root_id=parent.record.root_id
        )

    async def send_prompt(self, child: SessionWorker, text: str) -> QueueItem:
        item = QueueItem(session_id=child.session_id, message=UserMessage(text=text), source="agent")
        await child.enqueue(item)
        return item

    async def turn_ended(self, ref: SessionRef, result: TurnResult) -> None:
        if ref.parent_id is None or not result.final:
            return

        mode = ref.task_mode
        settled = task_result(ref.id, ref.agent, result)
        if mode == "foreground":
            parent = await self.sessions.worker(ref.parent_id)
            await parent.settle(ref.id, settled)
            child = await self.sessions.worker(ref.id)

            # 交给 run_in_background：Runner 关闭时会一并取消，不会在存储关闭后还在运行
            self.sessions.api.run_in_background(child.close(outcome=settled.status))
        elif mode == "background":
            parent = await self.sessions.worker(ref.parent_id)
            if not parent.open:
                return

            message = CustomMessage(
                "agent.result",
                data=settled.model_dump(mode="json"),
                for_model=json.dumps(settled.for_model(), ensure_ascii=False),
            )
            await parent.enqueue(QueueItem(session_id=parent.session_id, message=message, source="agent"))

    async def catch_up_after_restart(self) -> None:
        store = self.sessions.core.store
        for record in await store.list_sessions(status="open"):
            if record.parent_id is not None:
                continue

            worker = await self.sessions.worker(record.id)
            state = await worker.state()
            for wait in state.open_tasks():
                try:
                    child = await self.sessions.worker(wait.task_id)
                except KeyError:
                    continue

                child_state = await child.state()
                last = next(
                    (turn.result for turn in reversed(list(child_state.turns.values())) if turn.result is not None),
                    None,
                )
                if last is not None and last.final and child_state.turn is None:
                    await worker.settle(wait.task_id, task_result(child.session_id, child.record.agent, last))
                elif not child_state.turns and not await child.queued_items() and child.open:
                    await self.send_prompt(child, wait.prompt)

            awaited = {wait.task_id for wait in state.tasks.values()}
            for child_id in await self.sessions.children(record.id):
                child = await self.sessions.worker(child_id)
                child_state = await child.state()
                mode = child.record.config.task.mode if child.record.config.task else None
                if child.open and mode == "foreground" and child_id not in awaited and not child_state.turns:
                    await child.close(outcome="cancelled")

    async def info(self, worker: SessionWorker) -> SessionInfo:
        return await self.sessions.info(worker)


class TaskControlImpl:
    def __init__(self, ctx: RunContext, worker: SessionWorker, scope: CallScope | None) -> None:
        self._ctx = ctx
        self._worker = worker
        self._scope = scope
        self._tree = worker.sessions.tasks

    async def spawn(self, agent: Agent | str, *, background: bool = False, tools: list[str] | None = None) -> str:
        ctx = self._ctx
        scope = require_scope(self._scope, "ctx.tasks.spawn")
        index = scope.spawns
        scope.spawns += 1

        async def create() -> str:
            child = await self._tree.spawn(
                self._worker,
                agent,
                mode="background" if background else "foreground",
                tools=tools,
                parent_call_id=ctx.call.id if ctx.call else None,
            )
            return child.session_id

        return await ctx.step(f"work_agent_sdk.spawn.{index}", create)

    async def wait(self, task_id: str, prompt: str) -> TaskResult:
        ctx = self._ctx
        scope = require_scope(self._scope, "ctx.tasks.wait")
        call_state = scope.state
        ordinal = scope.next_ordinal()
        recorded = next((wait for wait in call_state.tasks if wait.ordinal == ordinal), None)
        if recorded is None:
            child = await self._child_worker(task_id)
            await self._worker.append(
                TaskAwaited(call_id=call_state.id, task_id=task_id, ordinal=ordinal, prompt=prompt, turn_id=ctx.turn_id)
            )
            await self._tree.send_prompt(child, prompt)
            raise Suspended("task")
        if recorded.task_id != task_id:
            raise ToolError("重新执行时等待的子会话与记录不一致", code="replay_mismatch")
        if recorded.result is None:
            raise Suspended("task")
        return recorded.result

    async def send(self, task_id: str, prompt: str) -> None:
        ctx = self._ctx
        scope = require_scope(self._scope, "ctx.tasks.send")
        count = scope.sends.get(task_id, 0)
        scope.sends[task_id] = count + 1
        child = await self._child_worker(task_id)

        async def send() -> str:
            item = await self._tree.send_prompt(child, prompt)
            return item.id

        await ctx.step(f"work_agent_sdk.send.{task_id}.{count}", send)

    async def close(self, task_id: str) -> None:
        child = await self._child_worker(task_id)
        await child.close(outcome="closed")

    async def get(self, task_id: str) -> SessionInfo | None:
        try:
            child = await self._child_worker(task_id)
        except ConfigError:
            return None
        return await self._tree.info(child)

    async def list(self) -> list[SessionInfo]:
        found = []
        for child_id in await self._worker.sessions.children(self._worker.session_id):
            found.append(await self._tree.info(await self._worker.sessions.worker(child_id)))
        return found

    async def _child_worker(self, task_id: str) -> Any:
        try:
            child = await self._worker.sessions.worker(task_id)
        except KeyError:
            raise ConfigError(f"子会话 {task_id} 不存在") from None
        if child.record.parent_id != self._worker.session_id:
            raise ConfigError(f"{task_id} 不是当前会话的子会话")
        return child
