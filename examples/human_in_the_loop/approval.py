import asyncio

from work_agent_sdk import Agent, Approval, Runner, tool
from work_agent_sdk.models import OpenAI


def build(version: str) -> str:
    print(f"Building {version}")
    return f"{version}-build"


@tool(description="Deploy the given version to the given environment")
async def deploy(ctx, version: str, env: str) -> str:
    artifact = await ctx.step("build", lambda: build(version))

    answer = await ctx.wait_for(
        Approval(title=f"Deploy {artifact} to {env}?", detail={"env": env}),
    )
    if not answer.approved:
        return f"The user declined the deployment: {answer.note}"
    return f"{artifact} deployed to {env}"


agent = Agent(
    "ops",
    model=OpenAI("gpt-5"),
    instructions="You are an ops assistant responsible for deployments.",
    tools=[deploy],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()

        result = await session.send("Deploy v1.4.2 to production.")
        while result.status == "waiting":
            request = result.pending[0]
            reply = input(f"{request.data['title']} [y/N] ").strip().lower()
            result = await session.answer(request.id, {"approved": reply == "y"})

        print(result.text)
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
