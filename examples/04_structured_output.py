"""结构化输出：让智能体返回程序可以直接处理的数据。"""

import asyncio
from typing import Literal

from pydantic import BaseModel

from work_agent_sdk import Agent, Runner
from work_agent_sdk.models import Claude


class Ticket(BaseModel):
    category: Literal["账户", "支付", "物流", "其他"]
    priority: int
    summary: str


agent = Agent(
    "triage",
    model=Claude("claude-sonnet-4-5"),
    instructions="把用户反馈整理成工单。priority 取 1 到 3，1 最紧急。",
    output=Ticket,
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()
        result = await session.send("付款后一直显示待付款，钱已经扣了，很着急。")

        ticket = Ticket.model_validate(result.data)
        print(ticket)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
