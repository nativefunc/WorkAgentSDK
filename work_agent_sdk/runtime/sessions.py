from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from work_agent_sdk.core.errors import ConfigError
from work_agent_sdk.core.events import SessionDeleted, SessionStarted
from work_agent_sdk.core.results import SessionConfig, SessionInfo, SessionRecord
from work_agent_sdk.core.utils import new_id
from work_agent_sdk.runtime.lifecycle import Lifecycle
from work_agent_sdk.runtime.tasks import TaskTree
from work_agent_sdk.runtime.turn.catalog import ExtensionTools
from work_agent_sdk.runtime.worker.worker import SessionWorker

if TYPE_CHECKING:
    from work_agent_sdk.runtime.api import RunnerAPIImpl
    from work_agent_sdk.runtime.runner_core import RunnerCore
    from work_agent_sdk.runtime.session import Session

logger = logging.getLogger("work_agent_sdk")


class Sessions:
    def __init__(self, core: RunnerCore) -> None:
        from work_agent_sdk.runtime.api import RunnerAPIImpl

        self.core = core
        self.lifecycle = Lifecycle(core.services)
        self.tasks = TaskTree(self)
        self.extension_tools = ExtensionTools()
        self.api: RunnerAPIImpl = RunnerAPIImpl(self)
        self._workers: dict[str, SessionWorker] = {}
        self._loading: dict[str, asyncio.Lock] = {}
        self.lifecycle.listen("turn_ended", self.tasks.turn_ended)

    async def worker(self, session_id: str) -> SessionWorker:
        worker = self._workers.get(session_id)
        if worker is not None:
            return worker

        lock = self._loading.setdefault(session_id, asyncio.Lock())
        async with lock:
            worker = self._workers.get(session_id)
            if worker is None:
                record = await self.core.store.get_session(session_id)
                if record is None:
                    raise KeyError(f"会话 {session_id} 不存在")

                worker = SessionWorker(self, record)
                if record.status == "closed":
                    self._loading.pop(session_id, None)
                    return worker

                self._workers[session_id] = worker

        return worker

    def release(self, worker: SessionWorker) -> None:
        if self._workers.get(worker.session_id) is worker:
            self.forget(worker.session_id)

    def forget(self, session_id: str) -> None:
        self._workers.pop(session_id, None)
        self._loading.pop(session_id, None)
        self.extension_tools.forget(session_id)

    def session(self, session_id: str) -> Session:
        from work_agent_sdk.runtime.session import Session

        return Session(self, session_id)

    async def create(
        self,
        agent: str,
        config: SessionConfig,
        *,
        parent_id: str | None = None,
        parent_call_id: str | None = None,
        root_id: str | None = None,
        session_id: str | None = None,
    ) -> SessionWorker:
        self.core.agent(agent)  # 未登记时抛出 ConfigError

        for name, value in config.resources.items():
            provider = self.core.provider(name)
            if provider is None:
                raise ConfigError(f"没有服务提供资源 {name!r}；请登记 provides={name!r} 的 Service")
            if parent_id is None:
                provider.check(value)

        session_id = session_id or new_id("ses_")
        record = SessionRecord(
            id=session_id,
            agent=agent,
            parent_id=parent_id,
            parent_call_id=parent_call_id,
            root_id=root_id or session_id,
            config=config,
        )
        await self.core.store.create_session(record)
        worker = self._workers[session_id] = SessionWorker(self, record)
        await worker.append(
            SessionStarted(agent=agent, parent_id=parent_id, root_id=record.root_id, forked_from=config.forked_from)
        )
        await self.lifecycle.notify("session_started", await worker.session_ref())
        return worker

    async def children(self, session_id: str) -> list[str]:
        return [record.id for record in await self.core.store.list_sessions(parent_id=session_id)]

    async def descendants(self, session_id: str) -> list[str]:
        found: list[str] = []
        frontier = [session_id]
        while frontier:
            current = frontier.pop()
            for child in await self.children(current):
                found.append(child)
                frontier.append(child)

        return found

    async def lineage(self, session_id: str) -> list[str]:
        ids = [session_id]
        record = await self.core.store.get_session(session_id)
        while record is not None and record.parent_id:
            ids.append(record.parent_id)
            record = await self.core.store.get_session(record.parent_id)

        return ids

    async def info(self, worker: SessionWorker) -> SessionInfo:
        record = worker.record
        state = await worker.state()
        if worker.segment is not None or (state.turn is not None and state.turn.phase == "running"):
            activity = "running"
        elif state.turn is not None and state.turn.phase == "parked":
            activity = "waiting"
        else:
            activity = "idle"

        agent = self.core.agent(record.agent)
        return SessionInfo(
            id=record.id,
            agent=record.agent,
            parent_id=record.parent_id,
            root_id=record.root_id,
            status=record.status,
            outcome=record.outcome,
            created_at=record.created_at,
            updated_at=record.updated_at,
            model=record.config.model or agent.model.id,
            thinking=record.config.thinking or agent.thinking,
            metadata=dict(record.config.metadata),
            resources=list(record.config.resources),
            activity=activity,
            queued=len(await worker.queued_items()),
            task=record.config.task,
        )

    async def delete(self, worker: SessionWorker) -> None:
        if worker.record.parent_id is not None:
            raise ConfigError("只能删除顶层会话；子会话随顶层会话一并删除")
        await worker.close(outcome=worker.record.outcome or "closed")
        await self._delete_tree(worker)

    async def _delete_tree(self, worker: SessionWorker) -> None:
        for child_id in await self.children(worker.session_id):
            await self._delete_tree(await self.worker(child_id))

        await self.lifecycle.notify("session_deleted", await worker.session_ref())
        await worker.append(SessionDeleted())
        await self.core.store.delete_session(worker.session_id)
        self.forget(worker.session_id)

    async def start(self) -> None:
        # 先恢复子任务的状态，再让服务启动后台循环（如定时任务），避免两者同时向会话投递
        await self.tasks.catch_up_after_restart()
        await self.lifecycle.notify("runner_started")
        for record in await self.core.store.list_sessions(status="open"):
            (await self.worker(record.id)).wake()

    async def shutdown(self) -> None:
        await self.lifecycle.notify("runner_stopping")
        await asyncio.gather(*(worker.shutdown() for worker in list(self._workers.values())), return_exceptions=True)
        # 后台任务可能还在用服务的存储：先停掉，再让服务在 runner_stopped 中关闭存储
        await self.api.cancel_background()
        await self.lifecycle.notify("runner_stopped")
