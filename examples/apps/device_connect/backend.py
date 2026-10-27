import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket
from pydantic import BaseModel

from work_agent_sdk import SRT, Agent, Device, Local, Runner, Shell, Workspace
from work_agent_sdk.events import NodeConnected, NodeDisconnected, NodeRefused
from work_agent_sdk.models import OpenAI

agent = Agent(
    "assistant",
    model=OpenAI("gpt-5"),
    instructions="You work on the user's computer.",
    tools=[Shell()],
)

DEVICES = Path("devices.json")


def device_name(user: str) -> str:
    return f"user-{user}"


def load_devices() -> list[str]:
    return json.loads(DEVICES.read_text()) if DEVICES.exists() else []


def save_device(name: str) -> None:
    DEVICES.write_text(json.dumps(sorted({*load_devices(), name})))


async def watch_devices(runner: Runner):
    async for event in runner.events():
        if isinstance(event, NodeConnected):
            print(f"{event.node} connected")
        elif isinstance(event, NodeDisconnected):
            print(f"{event.node} disconnected")
        elif isinstance(event, NodeRefused):
            print(f"{event.node} refused: {event.detail}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with Runner(agents=[agent], nodes=[Local()]) as runner:
        for name in load_devices():
            runner.nodes.add(Device(name, wait=30))

        watcher = asyncio.create_task(watch_devices(runner))
        app.state.runner = runner
        yield
        watcher.cancel()


app = FastAPI(lifespan=lifespan)


class TaskIn(BaseModel):
    text: str


@app.websocket("/work_agent_sdk/nodes")
async def nodes(websocket: WebSocket):
    await app.state.runner.nodes.websocket(websocket)


@app.post("/devices")
async def register_device(user: str):
    runner = app.state.runner
    name = device_name(user)
    if name not in runner.nodes.names():
        runner.nodes.add(Device(name, wait=30))
        save_device(name)
    return {"device": name, "token": await runner.nodes.issue_token(name)}


@app.get("/devices")
async def list_devices():
    return await app.state.runner.nodes.status()


@app.post("/tasks")
async def run_task(user: str, body: TaskIn):
    runner = app.state.runner
    name = device_name(user)
    if not runner.nodes.is_online(name):
        raise HTTPException(409, "Device is offline")

    session = await runner.new_session(
        workspace=Workspace("~/agent-workspace", node=name, sandbox=SRT()),
        metadata={"user_id": user},
    )
    result = await session.send(body.text)
    await session.close()
    return {"status": result.status, "text": result.text}
