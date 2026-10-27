import asyncio

from work_agent_sdk import Agent, Browser, BrowserUse, Runner
from work_agent_sdk.models import OpenAI

agent = Agent(
    "assistant",
    model=OpenAI("gpt-5"),
    instructions="You are working in the user's browser, which is already signed in to the user's accounts.",
    tools=[BrowserUse()],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(
            browser=Browser(cdp="http://127.0.0.1:9222", profile="shared"),
        )

        result = await session.send("Look at which tabs I have open and summarize the main content of each page.")
        print(result.text)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
