import asyncio

from work_agent_sdk import Agent, Runner, Toolset, tool
from work_agent_sdk.models import OpenAI


@tool(description="Look up an order")
def get_order(order_id: str) -> dict:
    return {"id": order_id, "status": "shipped"}


@tool(description="Cancel an order")
def cancel_order(order_id: str) -> str:
    return f"Order {order_id} cancelled"


class OrderTools(Toolset):
    name = "orders"

    async def tools(self, ctx):
        info = await ctx.session.info()
        if info.metadata.get("role") == "admin":
            return [get_order, cancel_order]
        return [get_order]


@tool(description="Get product inventory")
def get_stock(sku: str) -> int:
    return 42


@tool(description="Change product inventory")
def set_stock(sku: str, count: int) -> str:
    return f"Inventory of {sku} changed to {count}"


inventory = Toolset("inventory", tools=[get_stock, set_stock])


@tool(description="Get the shipment tracking history")
def track_parcel(tracking_no: str) -> str:
    return "Arrived at the Hangzhou sorting center"


@tool(description="Estimate the delivery time")
def estimate_delivery(tracking_no: str) -> str:
    return "Expected to arrive tomorrow"


logistics = Toolset(
    "logistics",
    tools=[track_parcel, estimate_delivery],
    description="Shipment tracking",
)

agent = Agent(
    "support",
    model=OpenAI("gpt-5"),
    instructions="You are an online store's customer service agent.",
    tools=[OrderTools(), inventory.only("get_*")],
)


async def main():
    async with Runner(agents=[agent], extensions=[logistics]) as runner:
        user = await runner.new_session(metadata={"role": "user"})
        print((await user.send("Please cancel order A1024.")).text)

        admin = await runner.new_session(metadata={"role": "admin"})
        print((await admin.send("Cancel order A1024, then check where package SF123 is.")).text)

        await user.close()
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
