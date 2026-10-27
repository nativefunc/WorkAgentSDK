from __future__ import annotations

import os
import time

from work_agent_sdk.core.sqlite import SqliteDB

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
  name TEXT PRIMARY KEY,
  data BLOB NOT NULL,
  updated_at REAL NOT NULL
);
"""


class MCPTokenStore:
    """Storage interface for MCP tokens; stores ciphertext. To use another database, subclass this and implement the methods below."""

    async def get(self, name: str) -> bytes | None:
        raise NotImplementedError

    async def put(self, name: str, data: bytes) -> None:
        raise NotImplementedError

    async def delete(self, name: str) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class SqliteMCPTokenStore(MCPTokenStore):
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.db = SqliteDB(path, schema=SCHEMA)

    def __repr__(self) -> str:
        return f"SqliteMCPTokenStore({str(self.db.path)!r})"

    async def get(self, name: str) -> bytes | None:
        row = await self.db.fetch_one("SELECT data FROM tokens WHERE name=?", (name,))
        return bytes(row["data"]) if row else None

    async def put(self, name: str, data: bytes) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO tokens(name, data, updated_at) VALUES (?,?,?)", (name, data, time.time())
        )

    async def delete(self, name: str) -> None:
        await self.db.execute("DELETE FROM tokens WHERE name=?", (name,))

    async def close(self) -> None:
        await self.db.close()
