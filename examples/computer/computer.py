import asyncio

from work_agent_sdk import Agent, Computer, ComputerUse, Runner
from work_agent_sdk.models import OpenAI

agent = Agent(
    "operator",
    model=OpenAI("gpt-5"),
    instructions="You operate apps on the computer using screenshots, the mouse and the keyboard.",
    tools=[ComputerUse()],
)


def ask_in_terminal(request) -> dict:
    if request.type == "AppAccess":
        apps = ", ".join(app["name"] for app in request.data["apps"])
        reply = input(f"Allow operating {apps}? Reason: {request.data['reason']} [y/N] ")
        return {"approved": reply.strip().lower() == "y"}
    input(f"Please handle this manually on the computer: {request.data['reason']}. Press Enter when done.")
    return {"done": True}


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(computer=Computer())

        result = await session.send("Open the system's built-in text editor, create a new file, and write: Meeting tomorrow at 10 a.m.")
        while result.status == "waiting":
            request = result.pending[0]
            result = await session.answer(request.id, ask_in_terminal(request))

        print(result.text)
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
