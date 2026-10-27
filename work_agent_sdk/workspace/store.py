from __future__ import annotations

import os
import time

from pydantic import BaseModel, Field

from work_agent_sdk.core.sqlite import SqliteDB
from work_agent_sdk.core.utils import new_id

MAX_OUTPUT_MB = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS processes (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at REAL NOT NULL,
  data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS processes_session ON processes(session_id);
CREATE INDEX IF NOT EXISTS processes_status ON processes(status);
"""


class ProcessRecord(BaseModel):
    """A process record. The executing node holds the true state; this is the state the backend last recorded."""

    id: str = Field(default_factory=lambda: new_id("p_"))
    session_id: str
    call_id: str | None = None
    key: str | None = None
    command: str
    node: str = ""
    path: str = ""
    background: bool = False
    # The workspace.process message in the conversation; only background processes have one
    message_id: str | None = None
    status: str = "running"
    exit_code: int | None = None
    max_output_bytes: int = MAX_OUTPUT_MB * 1024 * 1024
    output_offset: int = 0
    recorded_bytes: int = 0
    # Output position the model has read (bytes)
    seen_offset: int = 0
    started_at: float = Field(default_factory=time.time)
    ended_at: float | None = None


class ProcessStore:
    """Storage interface for process records. To use another database, subclass this and implement the methods below."""

    async def get(self, process_id: str) -> ProcessRecord | None:
        raise NotImplementedError

    async def put(self, record: ProcessRecord) -> None:
        raise NotImplementedError

    async def list(self, *, session_id: str | None = None, status: str | None = None) -> list[ProcessRecord]:
        """Return process records ordered by start time. session_id and status don't filter when None."""
        raise NotImplementedError

    async def delete(self, process_id: str) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class SqliteProcessStore(ProcessStore):
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.db = SqliteDB(path, schema=SCHEMA)

    def __repr__(self) -> str:
        return f"SqliteProcessStore({str(self.db.path)!r})"

    async def get(self, process_id: str) -> ProcessRecord | None:
        row = await self.db.fetch_one("SELECT data FROM processes WHERE id=?", (process_id,))
        return ProcessRecord.model_validate_json(row["data"]) if row else None

    async def put(self, record: ProcessRecord) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO processes(id, session_id, status, started_at, data) VALUES (?,?,?,?,?)",
            (record.id, record.session_id, record.status, record.started_at, record.model_dump_json()),
        )

    async def list(self, *, session_id: str | None = None, status: str | None = None) -> list[ProcessRecord]:
        clauses, values = [], []
        for column, value in (("session_id", session_id), ("status", status)):
            if value is not None:
                clauses.append(f"{column}=?")
                values.append(value)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = await self.db.fetch_all(f"SELECT data FROM processes{where} ORDER BY started_at", values)
        return [ProcessRecord.model_validate_json(row["data"]) for row in rows]

    async def delete(self, process_id: str) -> None:
        await self.db.execute("DELETE FROM processes WHERE id=?", (process_id,))

    async def close(self) -> None:
        await self.db.close()
