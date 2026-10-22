"""远程设备（后端连接设备）：设备程序监听一个地址，后端主动连接它。

1. 生成令牌，同时交给设备和后端：
       python -c "import secrets; print(secrets.token_urlsafe(32))" > ~/device-token
       export DEVICE_TOKEN=$(cat ~/device-token)

2. 在设备上启动设备程序（这里用本机演示）：
       python -m work_agent_sdk.cli device --name build-box \\
           --listen 127.0.0.1:7000 --token-file ~/device-token \\
           --workspace ~/device-workspace --sandbox srt

   监听 127.0.0.1 以外的地址时，需要 --tls-cert 和 --tls-key，后端使用 wss:// 连接。

3. 运行本例。
"""

import asyncio

from work_agent_sdk import SRT, Agent, Device, Local, Runner, Shell, Workspace
from work_agent_sdk.models import Claude

agent = Agent(
    "builder",
    model=Claude("claude-sonnet-4-5"),
    instructions="你在构建机上工作。",
    tools=[Shell()],
)

build_box = Device(
    "build-box",
    connect="ws://127.0.0.1:7000",
    token="${DEVICE_TOKEN}",  # 从环境变量读取
    wait=30,  # 设备不在线时最多等待的秒数
)


async def main():
    async with Runner(agents=[agent], nodes=[Local(), build_box]) as runner:
        session = await runner.new_session(
            workspace=Workspace("~/device-workspace", node="build-box", sandbox=SRT()),
        )

        result = await session.send("看一下这台机器的操作系统和 Python 版本。")
        print(result.text)

        # 应用也可以直接在设备上执行命令
        workspace = await session.workspace()
        run = await workspace.run("uname -a")
        print(run.stdout)

        print(await runner.nodes.status())
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
