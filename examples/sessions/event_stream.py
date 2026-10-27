import asyncio

from work_agent_sdk import Agent, Approval, CustomMessage, Runner, tool
from work_agent_sdk.events import (
    MessageCompleted,
    MessageStarted,
    MessageUpdated,
    QueueChanged,
    RequestClosed,
    RequestOpened,
    SessionEnded,
    TurnEnded,
    TurnStarted,
)
from work_agent_sdk.models import OpenAI


@tool(description="Get the weather for a city")
def get_weather(city: str) -> str:
    return f"{city}: sunny, 22°C"


@tool(description="Refund an order")
async def refund(ctx, order_id: str, amount: float) -> str:
    answer = await ctx.wait_for(Approval(title=f"Refund {amount} yuan for order {order_id}?"))
    return "Refunded" if answer.approved else "The user denied the refund"


agent = Agent(
    "support",
    model=OpenAI("gpt-5"),
    instructions="You are an online store's customer service agent.",
    tools=[get_weather, refund],
)


def summary(event) -> str:
    if isinstance(event, (MessageStarted, MessageCompleted)):
        return f"role={event.message.role}"
    if isinstance(event, MessageUpdated):
        return f"delta={event.delta}" if event.delta else f"changes={event.changes}"
    if isinstance(event, TurnStarted):
        return f"source={event.source}"
    if isinstance(event, TurnEnded):
        return f"status={event.result.status}"
    return ""


def render(event) -> str | None:
    if isinstance(event, MessageStarted):
        message = event.message
        if message.role == "assistant":
            return "\n"
        if message.role == "tool":
            return f"\n[Calling {message.tool_name}]"
        if message.role == "custom":
            return f"\n[{message.kind}] {message.data}"
    if isinstance(event, MessageUpdated):
        if event.delta and event.delta.get("kind") == "text":
            return event.delta["text"]
        if "data" in event.changes:
            return f"\n[Update] {event.changes['data']}"
    if isinstance(event, MessageCompleted):
        message = event.message
        if message.role == "tool":
            return f"\n[{message.tool_name} returned] {message.text}"
        if message.role == "custom":
            return f"\n[Done] {message.data}"
    if isinstance(event, RequestOpened):
        return f"\n[Awaiting approval] {event.request.data['title']}"
    if isinstance(event, RequestClosed):
        return f"\n[Approval closed] {event.status}"
    if isinstance(event, QueueChanged) and event.items:
        return f"\n[Queued messages] {len(event.items)}"
    if isinstance(event, TurnEnded):
        return f"\n[Turn ended] {event.result.status}\n"
    return None


async def frontend(session, after: int):
    async for event in session.events(after=after):
        text = render(event)
        if text:
            print(text, end="", flush=True)
        if isinstance(event, SessionEnded):
            break


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()

        print("All events in a turn:")
        async for event in session.send("What's the weather in Beijing today?"):
            print(f"{event.seq or '-':>3}  {event.type:<18} {summary(event)}")

        last_seq = [event async for event in session.events(live=False)][-1].seq

        print("\nWhat the frontend displays:")
        display = asyncio.create_task(frontend(session, after=last_seq))

        result = await session.send("Refund 99 yuan for order A1024.")
        result = await session.answer(result.pending[0].id, {"approved": True})

        first = session.send("Who pays for shipping?")
        second = session.send("How do I get an invoice?")
        await first
        await second

        message = await session.add_message(
            CustomMessage("shipping", data={"step": "Picked up"}, status="in_progress"),
        )
        await session.update_message(message.id, data={"step": "In transit"})
        await session.complete_message(
            message.id,
            data={"step": "Delivered"},
            for_model="Order A1024 has been delivered.",
        )

        await session.close()
        await display


if __name__ == "__main__":
    asyncio.run(main())
