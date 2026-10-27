import asyncio
from typing import Annotated

from pydantic import Field

from work_agent_sdk import Agent, Runner, ToolError, ToolResult, tool
from work_agent_sdk.models import OpenAI

ORDERS = {
    "A1024": {"id": "A1024", "status": "shipped", "items": ["keyboard", "mouse"]},
    "A1025": {"id": "A1025", "status": "awaiting payment", "items": ["monitor"]},
}


@tool(description="Get an order's status and items")
async def get_order(
    order_id: Annotated[str, Field(description="Order number, e.g. A1024")],
) -> dict:
    order = ORDERS.get(order_id)
    if order is None:
        raise ToolError(f"Order {order_id} does not exist", code="not_found")
    return order


@tool(description="List all of the user's orders")
async def list_orders() -> ToolResult:
    orders = list(ORDERS.values())
    return ToolResult(
        text=f"{len(orders)} orders in total: " + ", ".join(order["id"] for order in orders),
        data=orders,
    )


agent = Agent(
    "support",
    model=OpenAI("gpt-5"),
    instructions="You are an online store's customer service agent and only answer questions about orders.",
    tools=[get_order, list_orders],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()

        result = await session.send("What orders do I have? Has A1024 shipped? What about A9999?")
        print(result.text)

        for message in await session.history():
            if message.role == "tool":
                print(message.tool_name, message.error_code or "ok", message.data)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
