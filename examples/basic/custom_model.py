import asyncio

from work_agent_sdk import Agent, Runner, Usage
from work_agent_sdk.models import Finish, Model, TextDelta


class EchoModel(Model):
    async def stream(self, request):
        text = f"You said: {request.messages[-1].text}"
        for char in text:
            yield TextDelta(text=char)
        yield Finish(stop_reason="stop", usage=Usage(input_tokens=1, output_tokens=len(text)))


agent = Agent("echo", model=EchoModel("echo"))


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()
        result = await session.send("Hello")
        print(result.text)
        print(result.usage)
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
