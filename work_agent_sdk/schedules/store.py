from __future__ import annotations

import os
import time
from typing import Literal

from pydantic import BaseModel, Field

from work_agent_sdk.core.sqlite import SqliteDB
from work_agent_sdk.core.utils import new_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  created_at REAL NOT NULL,
  data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_session ON jobs(session_id);
"""


class ScheduleRecord(BaseModel):
    """
    A scheduled task. kind is once (run once at at), every (every every_minutes minutes) or daily (daily at the daily time,
    optionally limited to weekdays).
    """

    id: str = Field(default_factory=lambda: new_id("job_"))
    session_id: str
    prompt: str
    kind: Literal["once", "every", "daily"]
    at: float | None = None
    every_minutes: int | None = None
    daily: str | None = None
    weekdays: list[int] | None = None
    timezone: str = "UTC"
    next_run: float | None = None
    last_run: float | None = None
    paused: bool = False
    created_at: float = Field(default_factory=time.time)


class ScheduleStore:
    async def get(self, job_id: str) -> ScheduleRecord | None:
        raise NotImplementedError

    async def put(self, record: ScheduleRecord) -> None:
        raise NotImplementedError

    async def list(self, session_id: str | None = None) -> list[ScheduleRecord]:
        """Return scheduled tasks ordered by creation time. Returns tasks for all sessions when session_id is None."""
        raise NotImplementedError

    async def delete(self, job_id: str) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class SqliteScheduleStore(ScheduleStore):
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.db = SqliteDB(path, schema=SCHEMA)

    def __repr__(self) -> str:
        return f"SqliteScheduleStore({str(self.db.path)!r})"

    async def get(self, job_id: str) -> ScheduleRecord | None:
        row = await self.db.fetch_one("SELECT data FROM jobs WHERE id=?", (job_id,))
        return ScheduleRecord.model_validate_json(row["data"]) if row else None

    async def put(self, record: ScheduleRecord) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO jobs(id, session_id, created_at, data) VALUES (?,?,?,?)",
            (record.id, record.session_id, record.created_at, record.model_dump_json()),
        )

    async def list(self, session_id: str | None = None) -> list[ScheduleRecord]:
        if session_id is None:
            rows = await self.db.fetch_all("SELECT data FROM jobs ORDER BY created_at")
        else:
            rows = await self.db.fetch_all(
                "SELECT data FROM jobs WHERE session_id=? ORDER BY created_at", (session_id,)
            )
        return [ScheduleRecord.model_validate_json(row["data"]) for row in rows]

    async def delete(self, job_id: str) -> None:
        await self.db.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    async def close(self) -> None:
        await self.db.close()
