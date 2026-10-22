"""替换存储：会话、事件和消息队列默认保存在本机的 SQLite 中，可以换成自己的数据库。

本例用内存实现 Store，演示需要实现的方法和每个方法的约定；接入 PostgreSQL、Redis 等时按同样的约定实现。
同一份数据只能由一个 Runner 使用，替换存储后框架不再检查这一点。

另外演示 secret_key：MCP 的 OAuth 令牌加密后才保存，密钥可以来自环境变量或 KMS。
"""

import asyncio
import os
from collections import defaultdict

from work_agent_sdk import Agent, Runner
from work_agent_sdk.core.events import parse_event
from work_agent_sdk.events import Event
from work_agent_sdk.models import Claude
from work_agent_sdk.store import KeyProvider, QueueItem, SessionRecord, Store


class MemoryStore(Store):
    async def open(self) -> None:
        self.sessions: dict[str, SessionRecord] = {}
        self.event_rows: dict[str, list[tuple]] = defaultdict(list)
        self.queue: dict[str, QueueItem] = {}

    async def close(self) -> None:
        pass

    async def create_session(self, record: SessionRecord) -> None:
        self.sessions[record.id] = record.model_copy(deep=True)

    async def get_session(self, session_id: str) -> SessionRecord | None:
        record = self.sessions.get(session_id)
        return record.model_copy(deep=True) if record else None

    async def update_session(self, record: SessionRecord) -> None:
        self.sessions[record.id] = record.model_copy(deep=True)

    async def delete_session(self, session_id: str) -> None:
        # 同时删除该会话的事件和队列
        self.sessions.pop(session_id, None)
        self.event_rows.pop(session_id, None)
        for item_id in [i for i, item in self.queue.items() if item.session_id == session_id]:
            del self.queue[item_id]

    async def list_sessions(self, *, agent=None, parent_id=None, root_id=None, status=None, top_level=False):
        records = [
            record
            for record in self.sessions.values()
            if (agent is None or record.agent == agent)
            and (parent_id is None or record.parent_id == parent_id)
            and (root_id is None or record.root_id == root_id)
            and (status is None or record.status == status)
            and (not top_level or record.parent_id is None)
        ]
        return sorted(records, key=lambda record: record.created_at)

    async def append_event(self, session_id: str, event: Event) -> int:
        # 序号在会话内从 1 开始逐个递增；保存事件的类型、字段、turn_id 和时间
        rows = self.event_rows[session_id]
        seq = len(rows) + 1
        rows.append((seq, event.type, event.payload(), event.turn_id, event.ts))
        return seq

    async def events(self, session_id: str, *, after: int = 0, types: set[str] | None = None) -> list[Event]:
        return [
            parse_event(type_, payload, session_id=session_id, seq=seq, turn_id=turn_id, ts=ts)
            for seq, type_, payload, turn_id, ts in self.event_rows.get(session_id, [])
            if seq > after and (types is None or type_ in types)
        ]

    async def enqueue(self, item: QueueItem) -> None:
        self.queue[item.id] = item

    async def dequeue(self, item_id: str) -> bool:
        return self.queue.pop(item_id, None) is not None

    async def queued(self, session_id: str) -> list[QueueItem]:
        # priority 从大到小；相同时按加入的先后
        items = [item for item in self.queue.values() if item.session_id == session_id]
        return sorted(items, key=lambda item: (-item.priority, item.created_at))

    async def set_priority(self, item_id: str, priority: int) -> bool:
        if item_id not in self.queue:
            return False
        self.queue[item_id] = self.queue[item_id].model_copy(update={"priority": priority})
        return True

    async def clear_queue(self, session_id: str) -> list[QueueItem]:
        removed = await self.queued(session_id)
        for item in removed:
            del self.queue[item.id]
        return removed


class EnvKey(KeyProvider):
    """用 KMS 等管理密钥时，继承 KeyProvider 实现加解密。这里用 Fernet 演示，需要 pip install cryptography。"""

    def __init__(self, key: bytes):
        from cryptography.fernet import Fernet

        self.fernet = Fernet(key)

    def encrypt(self, data: bytes) -> bytes:
        return self.fernet.encrypt(data)

    def decrypt(self, data: bytes) -> bytes:
        return self.fernet.decrypt(data)


agent = Agent("assistant", model=Claude("claude-sonnet-4-5"), instructions="回答简洁。")


async def main():
    store = MemoryStore()
    # secret_key 也可以写成 "${WORK_AGENT_SECRET_KEY}"，从环境变量读取不少于 32 个字符的随机字符串
    secret_key = EnvKey(os.environ["FERNET_KEY"].encode()) if "FERNET_KEY" in os.environ else None

    async with Runner(agents=[agent], store=store, secret_key=secret_key) as runner:
        session = await runner.new_session()
        print((await session.send("你好")).text)
        print("保存的事件：", [event.type for event in await store.events(session.id)])
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
