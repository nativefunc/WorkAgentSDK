import asyncio

from work_agent_sdk import Agent, Continue, Deny, Hooks, Reply, Runner, TextPart, only_tools, tool
from work_agent_sdk.models import OpenAI

mini = OpenAI("gpt-5-mini")
backup = OpenAI("gpt-4.1")


@tool(description="Run a query on the given database and return the results")
async def query_sql(database: str, sql: str) -> str:
    return f"[{database}] results of {sql} ..."


@tool(description="Run SQL that modifies data on the given database")
async def execute_sql(database: str, sql: str) -> str:
    return f"[{database}] executed successfully, 12 rows affected"


class DemoHooks(Hooks):
    def __init__(self):
        self.modified = set()  # Turns that modified data and haven't verified the result yet

    async def before_turn(self, ctx, message):
        if message.text.strip() == "/help":
            return Reply("I can query and modify databases. The production database prod is read-only.")
        return None

    async def before_model(self, ctx, request):
        info = await ctx.session.info()
        if info.metadata.get("plan") == "free":
            return request.model_copy(update={"model": mini})
        return None

    @only_tools("execute_sql")
    async def before_tool(self, ctx, call):
        if call.args["database"] == "prod":
            return Deny("Direct changes to the production database aren't allowed; please submit a change request")
        return None

    async def after_tool(self, ctx, call, result):
        print(f"[audit] {call.name} {call.args} {'failed' if result.is_error else 'succeeded'}")
        if call.name == "execute_sql" and not result.is_error:
            self.modified.add(ctx.turn_id)
        if len(result.text) > 5000:
            return result.model_copy(update={"content": [TextPart(text=result.text[:5000] + "\n... (truncated)")]})
        return None

    async def before_turn_end(self, ctx, message):
        if ctx.turn_id in self.modified:
            self.modified.discard(ctx.turn_id)
            return Continue("You modified data. Use query_sql to confirm the change took effect, then answer the user.")
        return None

    async def on_model_error(self, ctx, request, error):
        if error.code in ("overloaded", "rate_limit"):
            return request.model_copy(update={"model": backup})
        return None


agent = Agent(
    "dba",
    model=OpenAI("gpt-5"),
    instructions="You are a database assistant.",
    tools=[query_sql, execute_sql],
)


async def main():
    async with Runner(agents=[agent], hooks=[DemoHooks()]) as runner:
        session = await runner.new_session(metadata={"plan": "free"})

        for text in [
            "/help",
            "In the staging database, set the status of expired coupons to expired.",
            "Delete logs older than 30 days in the prod database.",
        ]:
            print(f"> {text}")
            result = await session.send(text)
            print(f"{result.text}\n")

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
