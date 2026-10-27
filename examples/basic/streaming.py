import asyncio

from work_agent_sdk import Agent, Runner, tool
from work_agent_sdk.events import MessageStarted, MessageUpdated
from work_agent_sdk.models import OpenAI


@tool(description="Get the weather for a city")
def get_weather(city: str) -> str:
    return f"{city}: sunny, 25°C"


agent = Agent(
    "assistant",
    model=OpenAI("gpt-5"),
    instructions="You are an assistant.",
    tools=[get_weather],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()

        handle = session.send("What's the weather in Beijing and Shanghai today? Write a short post suitable for social media.")
        async for event in handle:
            if isinstance(event, MessageStarted) and event.message.role == "tool":
                print(f"\n[Calling tool {event.message.tool_name}]")
            elif isinstance(event, MessageUpdated) and event.delta and event.delta.get("kind") == "text":
                print(event.delta["text"], end="", flush=True)
        print()

        result = await handle
        print(result.status)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
