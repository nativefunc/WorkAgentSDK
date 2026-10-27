from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

from work_agent_sdk.core.messages import CustomMessage
from work_agent_sdk.core.service import UNSET, SessionRef
from work_agent_sdk.store import QueueItem

if TYPE_CHECKING:
    from work_agent_sdk.core.secrets import KeyProvider
    from work_agent_sdk.core.service import NodeLookup
    from work_agent_sdk.runtime.sessions import Sessions


class RunnerAPIImpl:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions
        self._background: set[asyncio.Task] = set()

    @property
    def secret_key(self) -> KeyProvider | None:
        return self._sessions.core.secret_key

    @property
    def nodes(self) -> NodeLookup:
        return self._sessions.core.nodes

    def files(self, name: str) -> Path:
        path = self._sessions.core.data_dir / "ext" / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def service(self, kind: type) -> Any:
        return self._sessions.core.service(kind)

    async def session(self, session_id: str) -> SessionRef | None:
        try:
            worker = await self._sessions.worker(session_id)
        except KeyError:
            return None
        return await worker.session_ref()

    async def lineage(self, session_id: str) -> list[str]:
        return await self._sessions.lineage(session_id)

    async def descendants(self, session_id: str) -> list[str]:
        return await self._sessions.descendants(session_id)

    async def resource(self, session_id: str, name: str) -> Any:
        worker = await self._sessions.worker(session_id)
        return await worker.resources.get(name)

    async def update_resource(self, session_id: str, name: str, config: dict[str, Any]) -> None:
        """Change the resource configuration saved in the session without affecting already-bound resource objects; the service providing the resource is responsible for applying the new configuration."""
        worker = await self._sessions.worker(session_id)
        worker.record.config.resources[name] = config
        await worker.save_record()

    async def model(self, session_id: str) -> Any:
        worker = await self._sessions.worker(session_id)
        return worker.model

    async def add_message(self, session_id: str, message: CustomMessage) -> CustomMessage:
        worker = await self._sessions.worker(session_id)
        return await worker.add_message(message)

    async def update_message(
        self, session_id: str, message_id: str, *, data: Any = UNSET, display: Any = UNSET, ephemeral: bool = False
    ) -> None:
        worker = await self._sessions.worker(session_id)
        await worker.update_message(message_id, data=data, display=display, ephemeral=ephemeral)

    async def complete_message(
        self,
        session_id: str,
        message_id: str,
        *,
        status: str = "completed",
        data: Any = UNSET,
        for_model: Any = UNSET,
    ) -> None:
        worker = await self._sessions.worker(session_id)
        await worker.complete_message(message_id, status=status, data=data, for_model=for_model)

    async def enqueue(
        self, session_id: str, message: CustomMessage, *, source: str, metadata: dict[str, Any] | None = None
    ) -> None:
        worker = await self._sessions.worker(session_id)
        await worker.enqueue(
            QueueItem(
                session_id=session_id,
                message=message,
                source=source,
                metadata=metadata or {},
            )
        )

    async def answer(self, session_id: str, request_id: str, value: Any) -> None:
        worker = await self._sessions.worker(session_id)
        await worker.answer(request_id, value)

    async def pending(self, session_id: str) -> list[Any]:
        worker = await self._sessions.worker(session_id)
        return await worker.pending(children=True)

    def run_in_background(self, coroutine: Coroutine[Any, Any, Any]) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coroutine)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task

    async def cancel_background(self) -> None:
        tasks = list(self._background)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=10)
