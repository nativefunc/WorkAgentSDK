"""在代码中创建子会话：由程序决定如何拆分任务，而不是由模型决定。

- 工具中用 ctx.tasks 创建子会话、交给它任务、等待结果
- 应用中用 session.spawn() 直接创建子会话
"""

import asyncio

from work_agent_sdk import Agent, Runner, tool
from work_agent_sdk.models import Claude

researcher = Agent(
    "researcher",
    model=Claude("claude-sonnet-4-5"),
    instructions="根据你掌握的知识，用三句话介绍指定公司的主营业务。",
)


@tool(description="分别调研几家公司")
async def research(ctx, companies: list[str]) -> list[dict]:
    reports = []
    for name in companies:
        # spawn、wait 在工具重新执行时不会重复执行；多个 wait 依次等待
        task_id = await ctx.tasks.spawn("researcher")
        result = await ctx.tasks.wait(task_id, f"介绍 {name}")
        reports.append({"company": name, **result.for_model()})
    return reports


analyst = Agent(
    "analyst",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是行业分析师。",
    tools=[research],
)


async def main():
    # ctx.tasks.spawn() 和 session.spawn() 使用的 Agent 必须在 Runner 中注册
    async with Runner(agents=[analyst, researcher]) as runner:
        session = await runner.new_session("analyst")
        result = await session.send("调研一下 NVIDIA 和 AMD，比较它们的业务重点。")
        print(result.text)

        # 应用直接创建子会话；report=False 时独立运行，结果不发回顶层会话
        child = await session.spawn("researcher", report=False)
        child_result = await child.send("介绍 Intel")
        print(child_result.text)

        for item in await session.children():
            print("子会话：", item.id)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
