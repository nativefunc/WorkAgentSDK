from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from work_agent_sdk.core.events import Event
from work_agent_sdk.core.messages import CustomMessage, UserMessage
from work_agent_sdk.core.results import SessionRecord
from work_agent_sdk.core.utils import new_id


class QueueItem(BaseModel):

    id: str = Field(default_factory=lambda: new_id("q_"))
    session_id: str
    message: UserMessage | CustomMessage
    source: str = "user"
    priority: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)

    @property
    def from_user(self) -> bool:
        return isinstance(self.message, UserMessage)

    def summary(self) -> dict[str, Any]:
        message = self.message
        text = (message.for_model or "") if isinstance(message, CustomMessage) else message.text

        return {
            "id": self.id,
            "source": self.source,
            "priority": self.priority,
            "kind": getattr(message, "kind", None),
            "text": text[:500],
            "created_at": self.created_at,
        }


class Store:
    async def open(self) -> None: ...
    async def close(self) -> None: ...

    async def create_session(self, record: SessionRecord) -> None:
        raise NotImplementedError

    async def get_session(self, session_id: str) -> SessionRecord | None:
        raise NotImplementedError

    async def update_session(self, record: SessionRecord) -> None:
        raise NotImplementedError

    async def delete_session(self, session_id: str) -> None:
        raise NotImplementedError

    async def list_sessions(
        self,
        *,
        agent: str | None = None,
        parent_id: str | None = None,
        root_id: str | None = None,
        status: str | None = None,
        top_level: bool = False,
    ) -> list[SessionRecord]:
        raise NotImplementedError

    async def append_event(self, session_id: str, event: Event) -> int:
        raise NotImplementedError

    async def events(self, session_id: str, *, after: int = 0, types: set[str] | None = None) -> list[Event]:
        raise NotImplementedError

    async def enqueue(self, item: QueueItem) -> None:
        raise NotImplementedError

    async def dequeue(self, item_id: str) -> bool:
        raise NotImplementedError

    async def queued(self, session_id: str) -> list[QueueItem]:
        raise NotImplementedError

    async def set_priority(self, item_id: str, priority: int) -> bool:
        raise NotImplementedError

    async def clear_queue(self, session_id: str) -> list[QueueItem]:
        raise NotImplementedError
