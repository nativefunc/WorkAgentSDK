"""接入不同的模型服务：Claude、OpenAI、兼容 OpenAI 接口的服务（DeepSeek、智谱等）、千问。

用法：
    python 08_providers.py claude      # 需要 ANTHROPIC_API_KEY，pip install anthropic
    python 08_providers.py openai      # 需要 OPENAI_API_KEY，pip install openai
    python 08_providers.py deepseek    # 需要 DEEPSEEK_API_KEY，pip install openai
    python 08_providers.py glm         # 需要 ZHIPU_API_KEY，pip install openai
    python 08_providers.py qwen        # 需要 DASHSCOPE_API_KEY，pip install dashscope
"""

import asyncio
import sys

from work_agent_sdk import Agent, Runner, tool
from work_agent_sdk.models import Claude, OpenAI, OpenAICompatible, Qwen


def make_model(name: str):
    if name == "claude":
        return Claude("claude-sonnet-4-5")
    if name == "openai":
        return OpenAI("gpt-5")  # 默认使用 Responses 接口；api="chat" 改用 Chat Completions
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
            thinking_format="thinking_type",  # 该服务开关思考的请求格式
        )
    if name == "qwen":
        return Qwen("qwen-max", input_types=("text",))  # 纯文本模型需要声明 input_types
    raise SystemExit(f"未知的模型服务：{name}")


@tool(description="查询城市的天气")
def get_weather(city: str) -> str:
    return f"{city}：晴，25°C"


async def main(name: str):
    agent = Agent("assistant", model=make_model(name), instructions="回答简洁。", tools=[get_weather])
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()
        result = await session.send("杭州今天天气怎么样？")
        print(result.status, result.text)
        if result.error:
            print(result.error.code, result.error.message)
        await session.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "claude"))
