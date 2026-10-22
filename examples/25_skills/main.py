"""技能：模型平时只看到每个技能的名称和简介，需要时加载完整说明，并运行技能附带的脚本。

技能目录是同目录下的 skills/。附带的脚本在工作区的沙箱中运行，运行前需要安装 srt。
"""

import asyncio
from pathlib import Path

from work_agent_sdk import SRT, Agent, Runner, Shell, Skills, Workspace
from work_agent_sdk.models import Claude

SKILLS = Path(__file__).with_name("skills")

agent = Agent(
    "writer",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是技术写作助手。",
    # 运行技能中的脚本需要 Shell，会话也需要工作区
    tools=[Shell(), Skills(str(SKILLS))],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(workspace=Workspace("~/work-agent-demo", sandbox=SRT()))

        # 模型根据技能的简介，自己决定是否加载
        result = await session.send("把这三条提交整理成版本说明：修复登录超时；新增导出 CSV；升级依赖。")
        print(result.text)

        # metadata 中指定技能时，这一轮开始前直接把技能内容交给模型
        result = await session.send("这次的版本号是多少比较合适？", metadata={"skills": ["release-notes"]})
        print(result.text)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
