import asyncio
from typing import Literal

from pydantic import BaseModel

from work_agent_sdk import Agent, Runner
from work_agent_sdk.models import OpenAI


class Ticket(BaseModel):
    category: Literal["account", "payment", "shipping", "other"]
    priority: int
    summary: str


agent = Agent(
    "triage",
    model=OpenAI("gpt-5"),
    instructions="Turn user feedback into a support ticket. priority is 1 to 3, with 1 the most urgent.",
    output=Ticket,
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()
        result = await session.send("After paying it still shows as awaiting payment, but the money has been taken. This is urgent.")

        ticket = Ticket.model_validate(result.data)
        print(ticket)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
