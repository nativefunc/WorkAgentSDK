"""共享文件夹：同一份数据在不同机器上的路径不同时，告诉模型每台机器上的路径。

框架不负责同步文件，共享文件夹需要事先挂载好，例如 NFS 或云盘。
本例假设数据集在本机的 ~/datasets，在 GPU 服务器上挂载在 /mnt/datasets。
GPU 服务器的接入方式见 18_device_listen.py。
"""

import asyncio

from work_agent_sdk import SRT, Agent, Device, Local, Runner, SharedFolder, Shell, Workspace
from work_agent_sdk.models import Claude

agent = Agent(
    "ml",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是机器学习工程师。",
    tools=[Shell()],
)


async def main():
    async with Runner(
        agents=[agent],
        nodes=[Local(), Device("gpu-a", connect="ws://127.0.0.1:7000", token="${DEVICE_TOKEN}")],
        shared_folders=[SharedFolder("datasets", {"local": "~/datasets", "gpu-a": "/mnt/datasets"})],
    ) as runner:
        session = await runner.new_session(
            workspace=Workspace("~/train", node="gpu-a", sandbox=SRT(read=["/mnt/datasets"])),
        )

        # 模型会得知数据集在 gpu-a 上的路径是 /mnt/datasets
        result = await session.send("统计 datasets 共享文件夹里每个子目录的文件数。")
        print(result.text)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
