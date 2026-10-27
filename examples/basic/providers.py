import asyncio
import sys

from work_agent_sdk import Agent, Runner, tool
from work_agent_sdk.models import Claude, OpenAI, OpenAICompatible, Qwen


def make_model(name: str):
    if name == "openai":
        return OpenAI("gpt-5")
    if name == "claude":
        return Claude("claude-sonnet-4-5")
    if name == "qwen":
        return Qwen("qwen-max", input_types=("text",))
    if name == "deepseek":
        return OpenAICompatible(
            "deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key="${DEEPSEEK_API_KEY}",
        )
    if name == "glm":
        return OpenAICompatible(
            "glm-4.6",
            base_url="https://open.bigmodel.cn/api/paas/v4",
            api_key="${ZHIPU_API_KEY}",
            thinking_format="thinking_type",
        )
    raise SystemExit(f"Unknown model provider: {name}")


@tool(description="Get the weather for a city")
def get_weather(city: str) -> str:
    return f"{city}: sunny, 25°C"


async def main(name: str):
    agent = Agent(
        "assistant",
        model=make_model(name),
        instructions="Keep answers concise.",
        tools=[get_weather],
    )
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()
        result = await session.send("What's the weather in Hangzhou today?")
        print(result.status, result.text)
        if result.error:
            print(result.error.code, result.error.message)
        await session.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "openai"))
