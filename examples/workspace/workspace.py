import asyncio

from work_agent_sdk import SRT, Agent, Runner, Shell, ViewImage, Workspace
from work_agent_sdk.models import OpenAI

agent = Agent(
    "dev",
    model=OpenAI("gpt-5"),
    instructions="You are a development assistant who completes tasks in the workspace.",
    tools=[Shell(timeout=60), ViewImage()],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(
            workspace=Workspace(
                "~/work-agent-demo",
                sandbox=SRT(network=["pypi.org", "files.pythonhosted.org"]),
                description="A Python practice project",
            ),
        )

        workspace = await session.workspace()

        await workspace.files.write("data/scores.csv", b"name,score\nalice,91\nbob,78\ncarol,85\n")

        result = await session.send("Read data/scores.csv, write a stats.py that computes the average score, and run it.")
        print(result.text)

        run = await workspace.run("python3 stats.py")
        print(run.exit_code, run.stdout)

        for item in await workspace.files.list("."):
            print(item.name, "directory" if item.is_dir else item.size)

        process = await workspace.start_process("python3 -u -m http.server 8765", key="preview")
        async for piece in process.output():
            print(piece.text, end="")
            if "Serving HTTP" in piece.text:
                break
        await process.kill()

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
