"""最小的智能体：发送一条消息，打印回答。"""

import asyncio

from work_agent_sdk import Agent, Runner
from work_agent_sdk.models import Claude

agent = Agent(
    "assistant",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是一名助手，回答简洁。",
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()

        result = await session.send("用一句话介绍 Python。")
        print(result.text)

        result = await session.send("它最常用在哪些领域？")
        print(result.text)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
