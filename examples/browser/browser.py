import asyncio
from pathlib import Path

from work_agent_sdk import Agent, Browser, BrowserPolicy, BrowserUse, Runner
from work_agent_sdk.models import OpenAI

agent = Agent(
    "researcher",
    model=OpenAI("gpt-5"),
    instructions="You are a research assistant. Use the browser to look things up, and cite source URLs in your answers.",
    tools=[BrowserUse()],
)

browser = Browser(
    node="local",
    headless=False,
    profile="research",
    policy=BrowserPolicy.standard(
        deny=["facebook.com", "*.facebook.com"],
        private=["127.0.0.1:*"],
    ),
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(browser=browser)

        result = await session.send("Open https://www.python.org and tell me the latest Python version number.")
        print(result.text)

        bound = await session.browser()
        page = await bound.perform("get_page_text", {})
        print(page["text"][:200])
        Path("python-org.jpg").write_bytes(await bound.screenshot())

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
