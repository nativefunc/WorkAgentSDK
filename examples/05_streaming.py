"""流式输出：模型的回答逐段打印，工具调用实时显示。"""

import asyncio

from work_agent_sdk import Agent, Runner, tool
from work_agent_sdk.events import MessageStarted, MessageUpdated
from work_agent_sdk.models import Claude


@tool(description="查询城市的天气")
def get_weather(city: str) -> str:
    return f"{city}：晴，25°C"


agent = Agent(
    "assistant",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是一名助手。",
    tools=[get_weather],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()

        handle = session.send("北京和上海今天的天气怎么样？写一段适合发朋友圈的文字。")
        async for event in handle:
            if isinstance(event, MessageStarted) and event.message.role == "tool":
                print(f"\n[调用工具 {event.message.tool_name}]")
            elif isinstance(event, MessageUpdated) and event.delta and event.delta.get("kind") == "text":
                print(event.delta["text"], end="", flush=True)
        print()

        result = await handle
        print("状态：", result.status)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
