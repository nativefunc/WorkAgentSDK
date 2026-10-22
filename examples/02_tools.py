"""函数工具：返回数据、返回错误，以及把数据单独交给前端。"""

import asyncio
from typing import Annotated

from pydantic import Field

from work_agent_sdk import Agent, Runner, ToolError, ToolResult, tool
from work_agent_sdk.models import Claude

ORDERS = {
    "A1024": {"id": "A1024", "status": "已发货", "items": ["键盘", "鼠标"]},
    "A1025": {"id": "A1025", "status": "待付款", "items": ["显示器"]},
}


@tool(description="查询订单的状态和商品")
async def get_order(order_id: Annotated[str, Field(description="订单号，例如 A1024")]) -> dict:
    order = ORDERS.get(order_id)
    if order is None:
        raise ToolError(f"订单 {order_id} 不存在", code="not_found")
    return order


@tool(description="列出用户的全部订单")
async def list_orders() -> ToolResult:
    orders = list(ORDERS.values())
    # 模型只看到摘要；完整数据保存在工具结果消息的 data 中，供前端展示
    return ToolResult(text=f"共 {len(orders)} 条订单：" + "、".join(o["id"] for o in orders), data=orders)


agent = Agent(
    "support",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是网店客服，只回答与订单有关的问题。",
    tools=[get_order, list_orders],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()

        result = await session.send("我有哪些订单？A1024 发货了吗？A9999 呢？")
        print(result.text)

        for message in await session.history():
            if message.role == "tool":
                print(message.tool_name, message.error_code or "ok", message.data)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
