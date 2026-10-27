import asyncio
import sqlite3
from typing import Annotated

from pydantic import BaseModel, Field

from work_agent_sdk import (
    Agent,
    ConfigError,
    CustomMessage,
    Runner,
    Service,
    Tool,
    ToolError,
    Toolset,
)
from work_agent_sdk.events import TurnEnded
from work_agent_sdk.models import OpenAI


class Database(BaseModel):
    name: str


class SQLiteDatabase:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)

    def tables(self) -> list[str]:
        rows = self.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        return [name for (name,) in rows]

    def query(self, sql: str) -> list:
        return self.connection.execute(sql).fetchall()

    def execute(self, sql: str) -> int:
        cursor = self.connection.execute(sql)
        self.connection.commit()
        return cursor.rowcount

    def close(self):
        self.connection.close()


class DatabaseService(Service):
    provides = "database"

    def check(self, config):
        name = Database.model_validate(config).name
        if not name.isidentifier():
            raise ConfigError(f"Invalid database name: {name}")

    async def runner_started(self):
        self.opened: dict[str, SQLiteDatabase] = {}
        self.api.run_in_background(self.watch_stock())

    async def bind(self, session):
        name = Database.model_validate(session.resources["database"]).name
        db = SQLiteDatabase(self.api.files("database") / f"{name}.db")
        db.execute("CREATE TABLE IF NOT EXISTS stock (sku TEXT PRIMARY KEY, count INTEGER)")
        db.execute("INSERT OR IGNORE INTO stock VALUES ('KB-01', 3), ('MS-02', 40)")
        self.opened[session.id] = db
        return db

    async def unbind(self, session, bound):
        self.opened.pop(session.id, None)
        bound.close()

    async def facts(self, session):
        db = self.opened.get(session.id)
        return {"tables": db.tables()} if db else None

    def render(self, facts):
        return "Tables in the database: " + ", ".join(facts["tables"])

    async def watch_stock(self):
        notified: set[str] = set()
        while True:
            await asyncio.sleep(5)
            for session_id, db in list(self.opened.items()):
                if session_id in notified:
                    continue
                low = db.query("SELECT sku, count FROM stock WHERE count < 5")
                if low:
                    message = CustomMessage(
                        "stock.low",
                        data=low,
                        for_model=f"Low stock: {low}",
                    )
                    await self.api.enqueue(session_id, message, source="stock")
                    notified.add(session_id)


class SQL(Toolset):
    name = "sql"
    description = "Query and modify the database"
    needs = (DatabaseService,)
    requires = frozenset({"database"})

    def __init__(self, *, writable: bool = False):
        super().__init__()
        self.writable = writable
        self._query = Tool(
            self.query,
            name="sql_query",
            description="Run read-only SQL and return the query results",
        )
        self._execute = Tool(
            self.execute,
            name="sql_execute",
            description="Run SQL that modifies data and return the number of affected rows",
        )

    async def tools(self, ctx):
        return [self._query, self._execute] if self.writable else [self._query]

    async def query(
        self,
        ctx,
        sql: Annotated[str, Field(description="SELECT statement")],
    ) -> list:
        if not sql.lstrip().lower().startswith("select"):
            raise ToolError("sql_query can only run SELECT statements", code="invalid_arguments")
        db = await ctx.resource("database")
        return db.query(sql)

    async def execute(
        self,
        ctx,
        sql: Annotated[str, Field(description="INSERT, UPDATE or DELETE statement")],
    ) -> int:
        db = await ctx.resource("database")
        return db.execute(sql)


agent = Agent(
    "ops",
    model=OpenAI("gpt-5"),
    instructions="You are a warehouse manager. When you receive a low-stock notification, suggest what to restock.",
    tools=[SQL(writable=True)],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(resources={"database": Database(name="shop")})

        result = await session.send("What products do we have, and how many of each are left?")
        print(result.text)

        async for event in session.events(after=0):
            if isinstance(event, TurnEnded) and event.session_id == session.id and event.turn_id != result.turn_id:
                print(event.result.text)
                break

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
