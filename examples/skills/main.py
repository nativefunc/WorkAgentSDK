import asyncio
from pathlib import Path

from work_agent_sdk import SRT, Agent, Runner, Shell, Skills, Workspace
from work_agent_sdk.models import OpenAI

agent = Agent(
    "writer",
    model=OpenAI("gpt-5"),
    instructions="You are a technical writing assistant.",
    tools=[Shell(), Skills(str(Path(__file__).with_name("skills")))],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(
            workspace=Workspace("~/work-agent-demo", sandbox=SRT()),
        )

        result = await session.send("Turn these three commits into release notes: fix login timeout; add CSV export; upgrade dependencies.")
        print(result.text)

        result = await session.send(
            "What version number would be appropriate for this release?",
            metadata={"skills": ["release-notes"]},
        )
        print(result.text)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
