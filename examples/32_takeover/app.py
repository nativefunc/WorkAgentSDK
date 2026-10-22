"""用户接管：智能体遇到登录、验证码等无法完成的操作时，发出 Takeover 请求，用户在网页上看到浏览器或屏幕的实时画面，直接操作。

后端负责两件事：把实时画面推送给前端，把用户的点击和输入转发给浏览器或电脑。用户完成后，答复请求，这一轮继续。

运行：
    pip install fastapi uvicorn playwright
    uvicorn app:app --port 8000

前端通过 WebSocket 连接 /sessions/{id}/takeover/{request_id}：
    收到二进制消息：一帧 JPEG 画面
    发送 {"type": "input", "action": "left_click", "args": {...}}：用户的操作
    发送 {"type": "done"}：用户完成
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from work_agent_sdk import Agent, Browser, BrowserUse, Computer, ComputerUse, Runner
from work_agent_sdk.models import Claude

agent = Agent(
    "assistant",
    model=Claude("claude-sonnet-4-5"),
    instructions="遇到需要登录或验证码的页面时，请用户接管。",
    tools=[BrowserUse(), ComputerUse()],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with Runner(agents=[agent]) as runner:
        app.state.runner = runner
        yield


app = FastAPI(lifespan=lifespan)


@app.post("/sessions")
async def create_session(computer: bool = False):
    session = await app.state.runner.new_session(
        browser=Browser(node="local"),
        computer=Computer(node="local") if computer else None,
    )
    return {"session_id": session.id}


@app.websocket("/sessions/{session_id}/takeover/{request_id}")
async def takeover(websocket: WebSocket, session_id: str, request_id: str):
    await websocket.accept()
    session = await app.state.runner.session(session_id)
    request = next(r for r in await session.pending() if r.id == request_id)

    if request.data["target"] == "browser":
        target = await session.browser()
    else:
        target = await session.computer()
        # 接管电脑屏幕：接管期间模型的电脑操作会等待；有人在看画面时自动延期
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
            # 浏览器的坐标为页面的 CSS 像素（BrowserFrame.viewport_width/height），
            # 电脑的坐标为屏幕的真实像素（ComputerFrame.real_width/height），前端按比例换算
            await target.user_input(message["action"], message["args"])
    finally:
        pushing.cancel()
        if request.data["target"] == "computer":
            await target.release_control()

    await session.answer(request_id, {"done": True}).queued()
    await websocket.close()
