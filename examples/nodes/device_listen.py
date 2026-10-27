import asyncio

from work_agent_sdk import SRT, Agent, Device, Local, Runner, Shell, Workspace
from work_agent_sdk.models import OpenAI

agent = Agent(
    "builder",
    model=OpenAI("gpt-5"),
    instructions="You work on the build machine.",
    tools=[Shell()],
)

build_box = Device(
    "build-box",
    connect="ws://127.0.0.1:7000",
    token="${DEVICE_TOKEN}",
    wait=30,
)


async def main():
    async with Runner(agents=[agent], nodes=[Local(), build_box]) as runner:
        session = await runner.new_session(
            workspace=Workspace("~/device-workspace", node="build-box", sandbox=SRT()),
        )

        result = await session.send("Check this machine's operating system and Python version.")
        print(result.text)

        workspace = await session.workspace()
        run = await workspace.run("uname -a")
        print(run.stdout)

        print(await runner.nodes.status())
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
