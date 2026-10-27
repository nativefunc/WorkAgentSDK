import asyncio
import os

from work_agent_sdk import Agent, Runner
from work_agent_sdk.models import ModelSettings, OpenAI

KEYS = {"main": "OPENAI_API_KEY", "backup": "BACKUP_OPENAI_API_KEY"}


async def api_key(ctx):
    if ctx is None:
        return os.environ[KEYS["main"]]
    info = await ctx.session.info()
    return os.environ[KEYS[info.metadata.get("key", "main")]]


gpt5 = OpenAI("gpt-5", api_key=api_key)
mini = OpenAI("gpt-5-mini", api_key=api_key)

agent = Agent(
    "analyst",
    model=gpt5,
    instructions="You are a data analyst. Keep answers concise.",
    thinking="medium",
    model_settings=ModelSettings(max_tokens=4096),
)


async def main():
    async with Runner(agents=[agent], models=[mini]) as runner:
        session = await runner.new_session(metadata={"key": "main"})

        result = await session.send("A bubble tea shop sells 300 cups a day at an average of 15 yuan per order. Roughly what is its monthly revenue?")
        print("gpt-5:", result.text)

        await session.update(model="gpt-5-mini", thinking="off")
        result = await session.send("What if the average order rises to 18 yuan?")
        print("gpt-5-mini:", result.text)

        await session.close()

    text = await mini.generate("Suggest a title for an article about a bubble tea shop's revenue.", system="Output only the title.")
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
