import asyncio

from work_agent_sdk import Agent, Runner
from work_agent_sdk.models import OpenAI

agent = Agent(
    "assistant",
    model=OpenAI("gpt-5"),
    instructions="You are an assistant. Keep answers concise.",
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()

        result = await session.send("Describe Python in one sentence.")
        print(result.text)

        result = await session.send("Where is it most commonly used?")
        print(result.text)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
