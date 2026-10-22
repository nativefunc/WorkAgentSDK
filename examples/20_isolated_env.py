"""隔离环境：为每个会话启动一个 Docker 容器，智能体在容器中工作，会话关闭时删除容器。

容器本身是隔离的，因此工作区可以不配置沙箱。

需要一个装好框架的镜像，容器启动后运行设备程序并监听端口，例如 Dockerfile：
    FROM python:3.12
    COPY . /sdk
    RUN pip install /sdk -r /sdk/requirements.txt
    CMD python -m work_agent_sdk.cli device --name "$DEVICE_NAME" --listen "127.0.0.1:$DEVICE_PORT" \\
        --token "$DEVICE_TOKEN" --workspace /work --sandbox none

构建：docker build -t work-agent-device .

本例用 --network host 启动容器，设备程序监听回环地址，不需要 TLS。--network host 只在 Linux 上可用；
其他环境中设备程序监听非回环地址时，需要 --tls-cert 和 --tls-key，后端用 wss:// 连接。
"""

import asyncio
import secrets
import socket

from work_agent_sdk import Agent, Device, Runner, Shell, Workspace
from work_agent_sdk.models import Claude

IMAGE = "work-agent-device"


async def docker(*args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode())
    return stdout.decode().strip()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ContainerProvider:
    """NodeProvider：为每个顶层会话创建一台机器，会话关闭时释放。"""

    isolated = True  # 声明环境本身是隔离的，工作区可以不配置沙箱

    async def acquire(self, root_id: str) -> Device:
        name = f"sandbox-{root_id}"
        token = secrets.token_urlsafe(32)
        port = free_port()
        await docker(
            "run", "-d", "--rm", "--network", "host", "--name", name,
            "-e", f"DEVICE_NAME={name}", "-e", f"DEVICE_PORT={port}", "-e", f"DEVICE_TOKEN={token}",
            IMAGE,
        )  # fmt: skip
        return Device(name, connect=f"ws://127.0.0.1:{port}", token=token, wait=60)

    async def release(self, root_id: str) -> None:
        await docker("rm", "-f", f"sandbox-{root_id}")


agent = Agent(
    "coder",
    model=Claude("claude-sonnet-4-5"),
    instructions="你在一个独立的容器中工作，可以随意安装软件。",
    tools=[Shell()],
)


async def main():
    async with Runner(agents=[agent], node_providers={"container": ContainerProvider()}) as runner:
        session = await runner.new_session(workspace=Workspace("/work", node="container"))

        result = await session.send("安装 cowsay，然后用它说一句你好。")
        print(result.text)

        await session.close()  # 触发 release，删除容器


if __name__ == "__main__":
    asyncio.run(main())
