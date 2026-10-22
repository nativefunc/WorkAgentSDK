from __future__ import annotations

import json
import os
import time
from typing import Any

from work_agent_sdk.core.sqlite import SqliteDB

SCHEMA = """
CREATE TABLE IF NOT EXISTS grants (
  root_id TEXT PRIMARY KEY,
  apps TEXT NOT NULL,
  system_keys INTEGER NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS takeovers (
  screen TEXT PRIMARY KEY,
  timeout REAL,
  started_at REAL NOT NULL
);
"""


class ComputerStore:
    """电脑扩展的存储接口。接入其他数据库时继承此类并实现以下方法。"""

    async def get_grants(self, root_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    async def put_grants(self, root_id: str, grants: dict[str, Any]) -> None:
        raise NotImplementedError

    async def delete_grants(self, root_id: str) -> None:
        raise NotImplementedError

    async def get_takeover(self, screen: str) -> dict[str, Any] | None:
        """返回 {"timeout": 秒数或 None}；该屏幕未被接管时返回 None。"""
        raise NotImplementedError

    async def put_takeover(self, screen: str, timeout: float | None) -> None:
        raise NotImplementedError

    async def delete_takeover(self, screen: str) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class SqliteComputerStore(ComputerStore):
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.db = SqliteDB(path, schema=SCHEMA)

    def __repr__(self) -> str:
        return f"SqliteComputerStore({str(self.db.path)!r})"

    async def get_grants(self, root_id: str) -> dict[str, Any] | None:
        row = await self.db.fetch_one("SELECT apps, system_keys FROM grants WHERE root_id=?", (root_id,))
        if row is None:
            return None
        return {"apps": json.loads(row["apps"]), "system_keys": bool(row["system_keys"])}

    async def put_grants(self, root_id: str, grants: dict[str, Any]) -> None:
        apps = json.dumps(grants.get("apps") or {}, ensure_ascii=False)
        await self.db.execute(
            "INSERT OR REPLACE INTO grants(root_id, apps, system_keys, updated_at) VALUES (?,?,?,?)",
            (root_id, apps, int(bool(grants.get("system_keys"))), time.time()),
        )

    async def delete_grants(self, root_id: str) -> None:
        await self.db.execute("DELETE FROM grants WHERE root_id=?", (root_id,))

    async def get_takeover(self, screen: str) -> dict[str, Any] | None:
        row = await self.db.fetch_one("SELECT timeout FROM takeovers WHERE screen=?", (screen,))
        return None if row is None else {"timeout": row["timeout"]}

    async def put_takeover(self, screen: str, timeout: float | None) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO takeovers(screen, timeout, started_at) VALUES (?,?,?)",
            (screen, timeout, time.time()),
        )

    async def delete_takeover(self, screen: str) -> None:
        await self.db.execute("DELETE FROM takeovers WHERE screen=?", (screen,))

    async def close(self) -> None:
        await self.db.close()
