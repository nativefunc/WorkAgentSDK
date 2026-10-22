from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from work_agent_sdk.core.errors import ConfigError
from work_agent_sdk.core.events import Event, parse_event
from work_agent_sdk.core.results import SessionConfig, SessionRecord
from work_agent_sdk.core.sqlite import SqliteDB
from work_agent_sdk.store.base import QueueItem, Store

SCHEMA_VERSION = "2"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  agent TEXT NOT NULL,
  parent_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
  parent_call_id TEXT,
  root_id TEXT NOT NULL,
  status TEXT NOT NULL,
  outcome TEXT,
  config TEXT NOT NULL,
  last_seq INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_parent ON sessions(parent_id);
CREATE INDEX IF NOT EXISTS sessions_root ON sessions(root_id);

CREATE TABLE IF NOT EXISTS events (
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  type TEXT NOT NULL,
  turn_id TEXT,
  ts REAL NOT NULL,
  data TEXT NOT NULL,
  PRIMARY KEY (session_id, seq)
);

CREATE TABLE IF NOT EXISTS queue (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  source TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 0,
  message TEXT NOT NULL,
  metadata TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS queue_order ON queue(session_id, priority DESC, created_at);
"""


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class LocalStore(Store):
    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self.directory = Path(os.path.expanduser(str(data_dir)))
        self.path = self.directory / "work-agent.db"
        self._db = SqliteDB(self.path, schema=SCHEMA)
        self._lock_file: Any = None

    def __repr__(self) -> str:
        return f"LocalStore({str(self.directory)!r})"

    async def _run(self, function: Any, *args: Any) -> Any:
        if self._lock_file is None:
            raise RuntimeError("存储尚未打开；请先调用 open()")
        return await self._db.run(function, *args)

    async def open(self) -> None:
        # 其中保存对话记录：新建时仅本机当前用户可访问（已存在的目录由部署者决定，不改动）
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._take_lock()
        try:
            await self._db.open()
            await self._db.run(self._check_version)
        except BaseException:
            await self.close()
            raise

    def _take_lock(self) -> None:
        lock_path = self.directory / "work-agent.lock"
        handle = open(lock_path, "a+")  # noqa: SIM115
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:  # pragma: no cover - Windows
            pass
        except OSError:
            handle.close()
            raise ConfigError(
                f"数据目录 {self.directory} 已被另一个 Runner 打开；请为每个 Runner 指定不同的 data_dir"
            ) from None

        self._lock_file = handle

    def _check_version(self) -> None:
        row = self.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is None:
            self.db.execute("INSERT INTO meta(key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        elif row["value"] != SCHEMA_VERSION:
            raise ConfigError(
                f"数据目录的版本为 {row['value']}，当前版本需要 {SCHEMA_VERSION}；框架不进行自动迁移，请使用新的 data_dir"
            )

    async def close(self) -> None:
        await self._db.close()
        if self._lock_file is not None:
            self._lock_file.close()
            self._lock_file = None

    @property
    def db(self) -> sqlite3.Connection:
        return self._db.connection

    @staticmethod
    def _session_row(row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            id=row["id"],
            agent=row["agent"],
            parent_id=row["parent_id"],
            parent_call_id=row["parent_call_id"],
            root_id=row["root_id"],
            status=row["status"],
            outcome=row["outcome"],
            config=SessionConfig.model_validate_json(row["config"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def create_session(self, record: SessionRecord) -> None:
        now = time.time()
        record.created_at = record.created_at or now
        record.updated_at = now

        def run() -> None:
            self.db.execute(
                "INSERT INTO sessions(id, agent, parent_id, parent_call_id, root_id, status, outcome, config,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    record.id,
                    record.agent,
                    record.parent_id,
                    record.parent_call_id,
                    record.root_id,
                    record.status,
                    record.outcome,
                    record.config.model_dump_json(),
                    record.created_at,
                    record.updated_at,
                ),
            )

        await self._run(run)

    async def get_session(self, session_id: str) -> SessionRecord | None:
        def run() -> SessionRecord | None:
            row = self.db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            return self._session_row(row) if row else None

        return await self._run(run)

    async def update_session(self, record: SessionRecord) -> None:
        record.updated_at = time.time()

        def run() -> None:
            self.db.execute(
                "UPDATE sessions SET status=?, outcome=?, config=?, updated_at=? WHERE id=?",
                (record.status, record.outcome, record.config.model_dump_json(), record.updated_at, record.id),
            )

        await self._run(run)

    async def delete_session(self, session_id: str) -> None:
        await self._run(lambda: self.db.execute("DELETE FROM sessions WHERE id=?", (session_id,)))

    async def list_sessions(
        self,
        *,
        agent: str | None = None,
        parent_id: str | None = None,
        root_id: str | None = None,
        status: str | None = None,
        top_level: bool = False,
    ) -> list[SessionRecord]:
        clauses, values = [], []
        for column, value in (("agent", agent), ("parent_id", parent_id), ("root_id", root_id), ("status", status)):
            if value is not None:
                clauses.append(f"{column}=?")
                values.append(value)

        if top_level:
            clauses.append("parent_id IS NULL")

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

        def run() -> list[SessionRecord]:
            rows = self.db.execute(f"SELECT * FROM sessions{where} ORDER BY created_at", values).fetchall()
            return [self._session_row(row) for row in rows]

        return await self._run(run)

    async def append_event(self, session_id: str, event: Event) -> int:
        payload = _dumps(event.payload())

        def run() -> int:
            db = self.db
            db.execute("BEGIN IMMEDIATE")

            try:
                row = db.execute("SELECT last_seq FROM sessions WHERE id=?", (session_id,)).fetchone()
                if row is None:
                    raise LookupError(f"会话 {session_id} 不存在")

                seq = row["last_seq"] + 1
                db.execute(
                    "INSERT INTO events(session_id, seq, type, turn_id, ts, data) VALUES (?,?,?,?,?,?)",
                    (session_id, seq, event.type, event.turn_id, event.ts, payload),
                )
                db.execute("UPDATE sessions SET last_seq=?, updated_at=? WHERE id=?", (seq, time.time(), session_id))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

            return seq

        return await self._run(run)

    async def events(self, session_id: str, *, after: int = 0, types: set[str] | None = None) -> list[Event]:
        def run() -> list[sqlite3.Row]:
            query = "SELECT * FROM events WHERE session_id=? AND seq>?"
            values: list[Any] = [session_id, after]
            if types:
                query += f" AND type IN ({','.join('?' * len(types))})"
                values.extend(sorted(types))

            return self.db.execute(query + " ORDER BY seq", values).fetchall()

        rows = await self._run(run)
        return [
            parse_event(
                row["type"],
                json.loads(row["data"]),
                session_id=session_id,
                seq=row["seq"],
                turn_id=row["turn_id"],
                ts=row["ts"],
            )
            for row in rows
        ]

    @staticmethod
    def _queue_row(row: sqlite3.Row) -> QueueItem:
        return QueueItem.model_validate(
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "source": row["source"],
                "priority": row["priority"],
                "message": json.loads(row["message"]),
                "metadata": json.loads(row["metadata"]),
                "created_at": row["created_at"],
            }
        )

    async def enqueue(self, item: QueueItem) -> None:
        def run() -> None:
            self.db.execute(
                "INSERT INTO queue(id, session_id, source, priority, message, metadata, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    item.id,
                    item.session_id,
                    item.source,
                    item.priority,
                    item.message.model_dump_json(),
                    _dumps(item.metadata),
                    item.created_at,
                ),
            )

        await self._run(run)

    async def dequeue(self, item_id: str) -> bool:
        def run() -> bool:
            return self.db.execute("DELETE FROM queue WHERE id=?", (item_id,)).rowcount > 0

        return await self._run(run)

    async def queued(self, session_id: str) -> list[QueueItem]:
        def run() -> list[QueueItem]:
            rows = self.db.execute(
                "SELECT * FROM queue WHERE session_id=? ORDER BY priority DESC, created_at", (session_id,)
            ).fetchall()
            return [self._queue_row(row) for row in rows]

        return await self._run(run)

    async def set_priority(self, item_id: str, priority: int) -> bool:
        def run() -> bool:
            return self.db.execute("UPDATE queue SET priority=? WHERE id=?", (priority, item_id)).rowcount > 0

        return await self._run(run)

    async def clear_queue(self, session_id: str) -> list[QueueItem]:
        def run() -> list[QueueItem]:
            db = self.db
            db.execute("BEGIN IMMEDIATE")

            try:
                rows = db.execute(
                    "SELECT * FROM queue WHERE session_id=? ORDER BY priority DESC, created_at", (session_id,)
                ).fetchall()
                db.execute("DELETE FROM queue WHERE session_id=?", (session_id,))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

            return [self._queue_row(row) for row in rows]

        return await self._run(run)
