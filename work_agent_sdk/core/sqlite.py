from __future__ import annotations

import asyncio
import os
import sqlite3
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


class SqliteDB:
    """A SQLite file. Opened and the schema run on first use (the schema should use CREATE ... IF NOT EXISTS); can be reopened after close()."""

    def __init__(self, path: str | os.PathLike[str], *, schema: str = "") -> None:
        self.path = Path(os.path.expanduser(str(path)))
        self.schema = schema
        self._executor: ThreadPoolExecutor | None = None
        self._connection: sqlite3.Connection | None = None
        self._opening = asyncio.Lock()

    def __repr__(self) -> str:
        return f"SqliteDB({str(self.path)!r})"

    @property
    def connection(self) -> sqlite3.Connection:
        """The current connection; only usable inside functions run by run()."""
        if self._connection is None:
            raise RuntimeError(f"{self.path} is not open yet")
        return self._connection

    async def open(self) -> None:
        async with self._opening:
            if self._executor is not None:
                return

            self.path.parent.mkdir(parents=True, exist_ok=True)
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"work-agent-db-{self.path.stem}")
            try:
                await asyncio.get_running_loop().run_in_executor(executor, self._connect)
            except BaseException:
                executor.shutdown(wait=False)
                raise

            self._executor = executor

    def _connect(self) -> None:
        connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=NORMAL")

        if self.schema:
            connection.executescript(self.schema)

        self._connection = connection

    async def close(self) -> None:
        executor, self._executor = self._executor, None
        if executor is None:
            return

        await asyncio.get_running_loop().run_in_executor(executor, self._disconnect)
        executor.shutdown(wait=True)

    def _disconnect(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    async def run(self, function: Callable[..., T], *args: Any) -> T:
        """Run function(*args) on the database thread, opening it first if needed."""
        if self._executor is None:
            await self.open()

        assert self._executor is not None
        return await asyncio.get_running_loop().run_in_executor(self._executor, function, *args)

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Execute a statement and return the number of affected rows."""
        return await self.run(lambda: self.connection.execute(sql, params).rowcount)

    async def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return await self.run(lambda: self.connection.execute(sql, params).fetchone())

    async def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return await self.run(lambda: self.connection.execute(sql, params).fetchall())
