import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket
from pydantic import BaseModel

from work_agent_sdk import Agent, Browser, BrowserUse, Computer, ComputerUse, Runner
from work_agent_sdk.models import OpenAI

agent = Agent(
    "assistant",
    model=OpenAI("gpt-5"),
    instructions="When you reach a page that requires signing in or entering a CAPTCHA, ask the user to take over.",
    tools=[BrowserUse(), ComputerUse()],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with Runner(agents=[agent]) as runner:
        app.state.runner = runner
        yield


app = FastAPI(lifespan=lifespan)


class MessageIn(BaseModel):
    text: str


@app.post("/sessions")
async def create_session(computer: bool = False):
    session = await app.state.runner.new_session(
        browser=Browser(node="local"),
        computer=Computer(node="local") if computer else None,
    )
    return {"session_id": session.id}


@app.post("/sessions/{session_id}/messages")
async def post_message(session_id: str, body: MessageIn):
    session = await app.state.runner.session(session_id)
    result = await session.send(body.text)
    takeovers = [request for request in result.pending if request.type == "Takeover"]
    return {
        "status": result.status,
        "text": result.text,
        "takeovers": [request.model_dump() for request in takeovers],
    }


@app.websocket("/sessions/{session_id}/takeover/{request_id}")
async def takeover(websocket: WebSocket, session_id: str, request_id: str):
    session = await app.state.runner.session(session_id)
    request = next((item for item in await session.pending() if item.id == request_id), None)
    if request is None:
        raise HTTPException(404)

    await websocket.accept()
    on_computer = request.data["target"] == "computer"
    target = await session.computer() if on_computer else await session.browser()
    if on_computer:
        await target.take_control(timeout=60)

    async def push_frames():
        async for frame in target.watch():
            await websocket.send_bytes(frame.image)

    pushing = asyncio.create_task(push_frames())
    try:
        while True:
            message = await websocket.receive_json()
            if message["type"] == "done":
                break
            await target.user_input(message["action"], message["args"])
    finally:
        pushing.cancel()
        if on_computer:
            await target.release_control()

    await session.answer(request_id, {"done": True}).queued()
    await websocket.close()
