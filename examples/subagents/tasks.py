import asyncio

from work_agent_sdk import Agent, Runner, tool
from work_agent_sdk.models import OpenAI

researcher = Agent(
    "researcher",
    model=OpenAI("gpt-5"),
    instructions="Describe the given company's main business in three sentences.",
)


@tool(description="Research several companies separately")
async def research(ctx, companies: list[str]) -> list[dict]:
    reports = []
    for name in companies:
        task_id = await ctx.tasks.spawn("researcher")
        result = await ctx.tasks.wait(task_id, f"Describe {name}")
        reports.append({"company": name, **result.for_model()})
    return reports


analyst = Agent(
    "analyst",
    model=OpenAI("gpt-5"),
    instructions="You are an industry analyst.",
    tools=[research],
)


async def main():
    async with Runner(agents=[analyst, researcher]) as runner:
        session = await runner.new_session("analyst")
        result = await session.send("Research NVIDIA and AMD and compare their business focus.")
        print(result.text)

        child = await session.spawn("researcher", report=False)
        child_result = await child.send("Describe Intel")
        print(child_result.text)

        for item in await session.children():
            print(item.id)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
