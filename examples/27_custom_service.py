"""自定义服务：为每个会话提供一个资源，把资源的状态告诉模型，并在后台运行任务。

本例的服务为每个租户提供一个 SQLite 数据库：
- bind / unbind：会话第一次使用时打开数据库，会话关闭时关闭
- facts / render：每一轮开始前，把数据库里有哪些表告诉模型
- run_in_background + enqueue：后台检查库存，不足时通知会话，会话自行开始一轮
"""

import asyncio
import sqlite3

from work_agent_sdk import Agent, ConfigError, CustomMessage, Runner, Service, tool
from work_agent_sdk.events import TurnEnded
from work_agent_sdk.models import Claude


class Database(Service):
    provides = "database"

    def check(self, config):
        if "tenant" not in config:
            raise ConfigError("database 资源需要 tenant")

    async def runner_started(self):
        self.watching: set[str] = set()
        self.api.run_in_background(self.watch_stock())

    async def bind(self, session):
        tenant = session.resources["database"]["tenant"]
        path = self.api.files("database") / f"{tenant}.db"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE IF NOT EXISTS stock (sku TEXT PRIMARY KEY, count INTEGER)")
        db.execute("INSERT OR IGNORE INTO stock VALUES ('KB-01', 3), ('MS-02', 40)")
        db.commit()
        self.watching.add(session.id)
        return db

    async def unbind(self, session, bound):
        self.watching.discard(session.id)
        bound.close()

    async def facts(self, session):
        return {"tables": ["stock(sku, count)"]}

    def render(self, facts):
        return "数据库中的表：" + "、".join(facts["tables"])

    async def watch_stock(self):
        while True:
            await asyncio.sleep(5)
            for session_id in list(self.watching):
                try:
                    db = await self.api.resource(session_id, "database")
                    low = db.execute("SELECT sku, count FROM stock WHERE count < 5").fetchall()
                    if low:
                        message = CustomMessage("stock.low", data=low, for_model=f"库存不足：{low}")
                        await self.api.enqueue(session_id, message, source="stock")
                        self.watching.discard(session_id)
                except Exception as error:  # noqa: BLE001  后台任务中未捕获的异常会让任务退出
                    print("检查库存失败：", error)


@tool(description="在数据库上执行只读 SQL", requires=["database"])
async def query(ctx, sql: str) -> list:
    db = await ctx.resource("database")
    return db.execute(sql).fetchall()


agent = Agent(
    "ops",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是仓库管理员。收到库存不足的通知时，给出补货建议。",
    tools=[query],
)


async def main():
    async with Runner(agents=[agent], services=[Database()]) as runner:
        session = await runner.new_session(resources={"database": {"tenant": "acme"}})

        result = await session.send("现在有哪些商品，各剩多少？")
        print(result.text)

        # 等后台检查发出通知，会话自行开始一轮
        async for event in session.events():
            if isinstance(event, TurnEnded) and event.session_id == session.id and event.turn_id != result.turn_id:
                print("收到库存通知后的回答：", event.result.text)
                break

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
