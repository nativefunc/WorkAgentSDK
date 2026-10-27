import asyncio

from work_agent_sdk import Agent, Runner, Subagents, tool
from work_agent_sdk.events import TurnEnded
from work_agent_sdk.models import OpenAI

REVIEWS = {
    "headphones": ["Great sound quality", "Battery life is shorter than advertised", "Ears hurt after wearing them a while"],
    "keyboard": ["Feels nice to type on", "Bluetooth occasionally disconnects"],
}


@tool(description="Read user reviews of a product")
def read_reviews(product: str) -> list[str]:
    return REVIEWS.get(product, [])


@tool(description="Get a product's sales over the last 30 days")
def sales(product: str) -> int:
    return {"headphones": 1200, "keyboard": 860}.get(product, 0)


@tool(description="Send a report to the team")
def send_report(title: str, body: str) -> str:
    return "Sent"


analyst = Agent(
    "review-analyst",
    model=OpenAI("gpt-5"),
    description="Read the user reviews of one product and summarize the main strengths and problems",
    instructions="After reading the reviews, summarize the strengths and problems in two or three sentences.",
    tools=[read_reviews],
)

reporter = Agent(
    "weekly-reporter",
    model=OpenAI("gpt-5"),
    description="Total the sales of all products and send them to the team as a weekly report",
    instructions="Look up the sales of each product, write a short weekly report and send it.",
    tools=[sales, send_report],
)

worker = Agent(
    "worker",
    model=OpenAI("gpt-5"),
    description="General-purpose worker",
    tools=[read_reviews, sales],
)

product_manager = Agent(
    "product-manager",
    model=OpenAI("gpt-5"),
    instructions="You are a product manager. Delegate to the right subagent based on the nature of the task.",
    tools=[Subagents(foreground=[analyst], background=[reporter], dynamic=worker)],
)


async def main():
    async with Runner(agents=[product_manager]) as runner:
        session = await runner.new_session()

        result = await session.send("Compare user feedback on the headphones and the keyboard: which needs more improvement? Also have someone write this week's sales report.")
        print(result.text)

        children = [await child.info() for child in await session.children()]
        if any(child.agent == "weekly-reporter" for child in children):
            async for event in session.events(after=0):
                if isinstance(event, TurnEnded) and event.session_id == session.id and event.turn_id != result.turn_id:
                    print(event.result.text)
                    break

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
