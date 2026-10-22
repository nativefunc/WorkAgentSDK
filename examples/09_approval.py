"""人工审批：工具执行有风险的操作前，暂停这一轮，等用户在终端确认。"""

import asyncio

from work_agent_sdk import Agent, Approval, Runner, tool
from work_agent_sdk.models import Claude

DEPLOYED = []


def build(version: str) -> str:
    print(f"  构建 {version}")
    return f"{version}-build"


@tool(description="把指定版本部署到指定环境")
async def deploy(ctx, version: str, env: str) -> str:
    # 用户答复后，工具会从头重新执行；放进 step 的操作只执行一次
    artifact = await ctx.step("build", lambda: build(version))

    answer = await ctx.wait_for(Approval(title=f"把 {artifact} 部署到 {env}？", detail={"env": env}))
    if not answer.approved:
        return f"用户拒绝了部署：{answer.note}"

    DEPLOYED.append((artifact, env))
    return f"{artifact} 已部署到 {env}"


agent = Agent(
    "ops",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是运维助手，负责部署。",
    tools=[deploy],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()

        result = await session.send("把 v1.4.2 部署到 production")
        while result.status == "waiting":
            request = result.pending[0]
            reply = input(f"{request.data['title']} [y/N] ").strip().lower()
            result = await session.answer(request.id, {"approved": reply == "y"})

        print(result.text)
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
