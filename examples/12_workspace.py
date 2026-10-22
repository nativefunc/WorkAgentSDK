"""工作区：智能体在指定目录中执行命令、读写文件；应用也可以直接使用同一个工作区。

命令在 srt 沙箱中运行，运行前需要安装 srt：npm install -g @anthropic-ai/sandbox-runtime
"""

import asyncio

from work_agent_sdk import SRT, Agent, Runner, Shell, ViewImage, Workspace
from work_agent_sdk.models import Claude

agent = Agent(
    "dev",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是开发助手，在工作区中完成任务。",
    tools=[Shell(timeout=60), ViewImage()],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(
            workspace=Workspace(
                "~/work-agent-demo",
                sandbox=SRT(network=["pypi.org", "files.pythonhosted.org"]),
                description="一个 Python 练习项目",
            ),
        )

        # 应用先准备文件
        workspace = await session.workspace()
        await workspace.files.write("data/scores.csv", b"name,score\nalice,91\nbob,78\ncarol,85\n")

        result = await session.send("读取 data/scores.csv，写一个 stats.py 计算平均分并运行。")
        print(result.text)

        # 应用直接执行命令、读取文件
        run = await workspace.run("python3 stats.py")
        print(run.exit_code, run.stdout)
        for item in await workspace.files.list("."):
            print(item.name, "目录" if item.is_dir else item.size)

        # 后台进程：启动后不等待结束，逐段读取输出
        process = await workspace.start_process("python3 -u -m http.server 8765", key="preview")
        async for piece in process.output():
            print(piece.text, end="")
            if "Serving HTTP" in piece.text:
                break
        await process.kill()

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
