from __future__ import annotations

import os
import time

from work_agent_sdk.core.sqlite import SqliteDB

SCHEMA = """
CREATE TABLE IF NOT EXISTS device_tokens (
  name TEXT PRIMARY KEY,
  digest TEXT NOT NULL,
  issued_at REAL NOT NULL
);
"""


class DeviceTokens:
    """设备令牌摘要的存储接口。接入其他数据库时继承此类并实现以下方法。"""

    async def get(self, name: str) -> str | None:
        raise NotImplementedError

    async def put(self, name: str, digest: str) -> None:
        raise NotImplementedError

    async def delete(self, name: str) -> None:
        raise NotImplementedError

    async def names(self) -> list[str]:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class SqliteDeviceTokens(DeviceTokens):
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.db = SqliteDB(path, schema=SCHEMA)

    def __repr__(self) -> str:
        return f"SqliteDeviceTokens({str(self.db.path)!r})"

    async def get(self, name: str) -> str | None:
        row = await self.db.fetch_one("SELECT digest FROM device_tokens WHERE name=?", (name,))
        return str(row["digest"]) if row else None

    async def put(self, name: str, digest: str) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO device_tokens(name, digest, issued_at) VALUES (?,?,?)", (name, digest, time.time())
        )

    async def delete(self, name: str) -> None:
        await self.db.execute("DELETE FROM device_tokens WHERE name=?", (name,))

    async def names(self) -> list[str]:
        return [str(row["name"]) for row in await self.db.fetch_all("SELECT name FROM device_tokens ORDER BY name")]

    async def close(self) -> None:
        await self.db.close()
