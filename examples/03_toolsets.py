"""工具集：按会话提供不同的工具、只提供工具集中的部分工具，以及按需加载大量工具（ToolSearch）。"""

import asyncio

from work_agent_sdk import Agent, Runner, Toolset, tool
from work_agent_sdk.models import Claude


@tool(description="查询订单")
def get_order(order_id: str) -> dict:
    return {"id": order_id, "status": "已发货"}


@tool(description="取消订单")
def cancel_order(order_id: str) -> str:
    return f"订单 {order_id} 已取消"


class OrderTools(Toolset):
    """普通用户只能查询订单，管理员还能取消订单。"""

    name = "orders"

    async def tools(self, ctx):
        info = await ctx.session.info()
        if info.metadata.get("role") == "admin":
            return [get_order, cancel_order]
        return [get_order]


@tool(description="查询商品库存")
def get_stock(sku: str) -> int:
    return 42


@tool(description="修改商品库存")
def set_stock(sku: str, count: int) -> str:
    return f"{sku} 库存已改为 {count}"


inventory = Toolset("inventory", tools=[get_stock, set_stock])


@tool(description="查询物流轨迹")
def track_parcel(tracking_no: str) -> str:
    return "已到达杭州转运中心"


@tool(description="预估送达时间")
def estimate_delivery(tracking_no: str) -> str:
    return "预计明天送达"


logistics = Toolset("logistics", tools=[track_parcel, estimate_delivery], description="物流查询")

agent = Agent(
    "support",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是网店客服。",
    # only() 和 exclude() 按名称筛选工具集中的工具，支持 * 通配
    tools=[OrderTools(), inventory.only("get_*")],
)


async def main():
    # extensions 中的工具不直接发给模型，模型需要时通过 tool_search 搜索并加载
    async with Runner(agents=[agent], extensions=[logistics]) as runner:
        user = await runner.new_session(metadata={"role": "user"})
        print((await user.send("帮我取消订单 A1024。")).text)

        admin = await runner.new_session(metadata={"role": "admin"})
        print((await admin.send("取消订单 A1024，再查一下快递 SF123 到哪了。")).text)

        await user.close()
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
