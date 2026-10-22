"""子智能体：主智能体把任务交给子智能体。

- 前台：主智能体等子智能体完成，拿到结果后继续；一次委派多个时同时执行
- 后台：委派后主智能体立即继续；子智能体每完成一轮，结果作为消息发回主智能体
- 动态：主智能体从模板的工具中挑选子智能体可以使用的工具
"""

import asyncio

from work_agent_sdk import Agent, Runner, Subagents, tool
from work_agent_sdk.events import TurnEnded
from work_agent_sdk.models import Claude

REVIEWS = {
    "耳机": ["音质很好", "续航比宣传的短", "佩戴久了耳朵疼"],
    "键盘": ["手感不错", "蓝牙偶尔断连"],
}


@tool(description="读取某个商品的用户评价")
def read_reviews(product: str) -> list[str]:
    return REVIEWS.get(product, [])


@tool(description="查询某个商品近 30 天的销量")
def sales(product: str) -> int:
    return {"耳机": 1200, "键盘": 860}.get(product, 0)


@tool(description="给团队发送一份报告")
def send_report(title: str, body: str) -> str:
    return "已发送"


analyst = Agent(
    "review-analyst",
    model=Claude("claude-sonnet-4-5"),
    description="读取一个商品的用户评价，总结主要优点和问题",
    instructions="读取评价后，用两三句话总结优点和问题。",
    tools=[read_reviews],
)

reporter = Agent(
    "weekly-reporter",
    model=Claude("claude-sonnet-4-5"),
    description="汇总所有商品的销量，写成周报发给团队，耗时较长",
    instructions="查询每个商品的销量，写一份简短的周报并发送。",
    tools=[sales, send_report],
)

worker = Agent(
    "worker",
    model=Claude("claude-sonnet-4-5"),
    description="通用执行者",
    tools=[read_reviews, sales],
)

product_manager = Agent(
    "product-manager",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是产品经理。按任务的性质交给合适的子智能体。",
    tools=[Subagents(foreground=[analyst], background=[reporter], dynamic=worker)],
)


async def main():
    async with Runner(agents=[product_manager]) as runner:
        session = await runner.new_session()

        result = await session.send("对比耳机和键盘的用户反馈，哪个更需要改进？另外安排人写这周的销量周报。")
        print(result.text)

        # 后台子智能体完成后，结果会让会话自行开始一轮，这一轮的输出通过事件获取
        async for event in session.events():
            if isinstance(event, TurnEnded) and event.session_id == session.id and event.turn_id != result.turn_id:
                print("处理后台结果的一轮：", event.result.text)
                break

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
