"""远程设备（设备连接后端）：用户在自己的电脑上运行设备程序，主动连接后端，智能体在用户的电脑上工作。

设备主动连接后端，后端不需要能访问用户的电脑。

运行后端：
    pip install fastapi uvicorn
    uvicorn backend:app --port 8000

为用户签发令牌：
    curl -X POST "http://127.0.0.1:8000/devices?user=alice"

在用户电脑上运行设备程序（README 中有完整说明）：
    export WORK_AGENT_DEVICE_TOKEN=<上一步返回的令牌>
    python -m work_agent_sdk.cli device --name user-alice \\
        --url ws://127.0.0.1:8000/work_agent_sdk/nodes \\
        --workspace ~/agent-workspace --sandbox srt

让智能体在用户电脑上工作：
    curl -X POST "http://127.0.0.1:8000/tasks?user=alice" -H "content-type: application/json" \\
        -d '{"text": "在工作区里新建 notes.md，写入今天的日期"}'
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket
from pydantic import BaseModel

from work_agent_sdk import SRT, Agent, Device, Local, Runner, Shell, Workspace
from work_agent_sdk.events import NodeConnected, NodeDisconnected, NodeRefused
from work_agent_sdk.models import Claude

agent = Agent(
    "assistant",
    model=Claude("claude-sonnet-4-5"),
    instructions="你在用户的电脑上工作。",
    tools=[Shell()],
)


def device_name(user: str) -> str:
    return f"user-{user}"


async def watch_devices(runner: Runner):
    async for event in runner.events():
        if isinstance(event, NodeConnected):
            print(f"{event.node} 已上线")
        elif isinstance(event, NodeDisconnected):
            print(f"{event.node} 已下线")
        elif isinstance(event, NodeRefused):
            print(f"{event.node} 连接被拒绝：{event.detail}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with Runner(agents=[agent], nodes=[Local()]) as runner:
        # runner.nodes.add() 注册的设备只保存在内存中，后端重启后需要重新注册；
        # 已签发的令牌保存在数据目录中，重启后仍然有效
        for user in load_known_users():
            runner.nodes.add(Device(device_name(user)))
        watcher = asyncio.create_task(watch_devices(runner))
        app.state.runner = runner
        yield
        watcher.cancel()


app = FastAPI(lifespan=lifespan)


def load_known_users() -> list[str]:
    # 实际项目中从数据库读取已接入设备的用户
    return []


@app.websocket("/work_agent_sdk/nodes")
async def nodes(websocket: WebSocket):
    await app.state.runner.nodes.websocket(websocket)


@app.post("/devices")
async def register_device(user: str):
    runner = app.state.runner
    name = device_name(user)
    if name not in runner.nodes.names():
        runner.nodes.add(Device(name, wait=30))
    # 每次调用都会签发新令牌，旧令牌立即失效
    return {"device": name, "token": await runner.nodes.issue_token(name)}


@app.get("/devices")
async def list_devices():
    return await app.state.runner.nodes.status()


class TaskIn(BaseModel):
    text: str


@app.post("/tasks")
async def run_task(user: str, body: TaskIn):
    runner = app.state.runner
    name = device_name(user)
    if not runner.nodes.is_online(name):
        raise HTTPException(409, "设备不在线")

    session = await runner.new_session(
        workspace=Workspace("~/agent-workspace", node=name, sandbox=SRT()),
        metadata={"user_id": user},
    )
    result = await session.send(body.text)
    await session.close()
    return {"status": result.status, "text": result.text}
