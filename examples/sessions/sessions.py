import asyncio

from work_agent_sdk import Agent, CustomMessage, Runner
from work_agent_sdk.models import OpenAI

agent = Agent("support", model=OpenAI("gpt-5"), instructions="You are an online store's customer service agent.")


async def first_run() -> str:
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(metadata={"user_id": "u_1024"})
        result = await session.send("I want to buy a 27-inch monitor with a budget of 2000 yuan.")
        print(result.text)
        return session.id


async def second_run(session_id: str):
    async with Runner(agents=[agent]) as runner:
        session = await runner.session(session_id)
        print((await session.info()).metadata)

        await session.add_message(
            CustomMessage(
                "coupon_issued",
                data={"code": "SAVE200", "amount": 200},
                for_model="The user received a 200 yuan coupon, SAVE200.",
            )
        )
        result = await session.send("How much budget does the coupon free up?")
        print(result.text)

        handles = [
            session.send("Recommend one."),
            session.send("Does it support 7-day no-questions-asked returns?"),
            session.send("How do I get an invoice?", priority=10),
        ]
        for handle in handles:
            await handle.queued()
        print([item.message.text for item in await session.queue.list()])
        for handle in handles:
            print((await handle).text)

        user_messages = [message for message in await session.history() if message.role == "user"]

        removed = await session.rewind(user_messages[-1].id)
        print(f"Rewound {len(removed)} messages")

        copy = await session.fork(user_messages[0].id)
        print(copy.id)

        print(await session.usage())
        await copy.close()
        await session.close()


async def main():
    session_id = await first_run()
    await second_run(session_id)


if __name__ == "__main__":
    asyncio.run(main())
