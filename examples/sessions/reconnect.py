import asyncio

from work_agent_sdk import Agent, Runner
from work_agent_sdk.events import (
    MessageCompleted,
    MessageStarted,
    MessageUpdated,
    TurnEnded,
)
from work_agent_sdk.models import OpenAI

agent = Agent("writer", model=OpenAI("gpt-5"), instructions="You are a writing assistant.")


class Screen:
    def __init__(self):
        self.answers: dict[str, str] = {}
        self.last_seq = 0

    def apply(self, event):
        if event.seq is not None:
            self.last_seq = event.seq
        if isinstance(event, MessageStarted) and event.message.role == "assistant":
            self.answers[event.message.id] = ""
        elif isinstance(event, MessageUpdated) and event.message is not None:
            self.answers[event.message_id] = event.message.text
        elif isinstance(event, MessageUpdated) and event.delta and event.delta.get("kind") == "text":
            self.answers[event.message_id] = self.answers.get(event.message_id, "") + event.delta["text"]
        elif isinstance(event, MessageCompleted) and event.message.role == "assistant":
            self.answers[event.message.id] = event.message.text


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()
        screen = Screen()

        handle = session.send("Write about 200 words introducing West Lake in Hangzhou.")
        await handle.queued()

        async for event in session.events(after=screen.last_seq):
            screen.apply(event)
            if isinstance(event, TurnEnded) or sum(len(text) for text in screen.answers.values()) >= 100:
                break
        print(f"{sum(len(text) for text in screen.answers.values())} characters displayed at disconnect")

        await asyncio.sleep(0.5)

        async for event in session.events(after=screen.last_seq, snapshot=True):
            screen.apply(event)
            if isinstance(event, TurnEnded):
                break

        result = await handle
        displayed = list(screen.answers.values())[-1]
        print("Displayed content matches the answer:", displayed == result.text)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
