"""模型设置：思考强度、模型参数、按租户使用不同密钥、对话中切换模型、单独调用模型。"""

import asyncio
import os

from pydantic import BaseModel

from work_agent_sdk import Agent, Runner
from work_agent_sdk.models import Claude, ModelSettings

TENANT_KEYS = {"acme": os.environ.get("ACME_ANTHROPIC_KEY", ""), "globex": os.environ.get("GLOBEX_ANTHROPIC_KEY", "")}


async def tenant_key(ctx):
    # 每次调用模型时取密钥。ctx 为 None 表示在会话之外调用，例如 model.generate()
    if ctx is None:
        return os.environ["ANTHROPIC_API_KEY"]
    info = await ctx.session.info()
    return TENANT_KEYS.get(info.metadata.get("tenant"), os.environ["ANTHROPIC_API_KEY"])


sonnet = Claude("claude-sonnet-4-5", api_key=tenant_key)
haiku = Claude("claude-haiku-4-5", api_key=tenant_key)

agent = Agent(
    "analyst",
    model=sonnet,
    instructions="你是数据分析师，回答简洁。",
    thinking="medium",
    model_settings=ModelSettings(max_tokens=4096),
)


class Title(BaseModel):
    title: str


async def main():
    # 会话中可以切换到的其他模型，需要在 Runner 中列出
    async with Runner(agents=[agent], models=[haiku]) as runner:
        session = await runner.new_session(metadata={"tenant": "acme"})

        result = await session.send("一家奶茶店日销 300 杯，客单价 15 元，月营业额大约多少？")
        print("sonnet：", result.text)

        await session.update(model="claude-haiku-4-5", thinking="off")
        result = await session.send("如果客单价涨到 18 元呢？")
        print("haiku：", result.text)

        print((await session.info()).model)
        await session.close()

    # 不经过会话，单独调用一次模型
    text = await haiku.generate("为一篇讲奶茶店营收的文章拟一个标题。", system="只输出标题。")
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
