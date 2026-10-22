"""Web 后端：用 FastAPI 提供对话接口，用 SSE 把智能体的输出推送给浏览器。

运行：
    pip install fastapi uvicorn
    uvicorn app:app --port 8000     # 只能单进程运行，不要加 --workers
然后打开 http://127.0.0.1:8000
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi import Request as HttpRequest
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from work_agent_sdk import (
    Agent,
    Approval,
    InvalidAnswer,
    RequestClosed,
    Runner,
    SessionClosed,
    tool,
)
from work_agent_sdk.models import Claude


@tool(description="给客户退款")
async def refund(ctx, order_id: str, amount: float) -> str:
    answer = await ctx.wait_for(Approval(title=f"给订单 {order_id} 退款 {amount} 元？"))
    if not answer.approved:
        return "退款被拒绝"
    return f"已给订单 {order_id} 退款 {amount} 元"


agent = Agent(
    "support",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是网店客服，可以办理退款。",
    tools=[refund],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with Runner(agents=[agent]) as runner:
        app.state.runner = runner
        yield


app = FastAPI(lifespan=lifespan)


def current_user(request: HttpRequest) -> str:
    # 示例用请求头代替登录校验
    return request.headers.get("x-user-id") or request.query_params.get("user") or "demo"


async def open_session(request: HttpRequest, session_id: str):
    try:
        session = await request.app.state.runner.session(session_id)
    except KeyError:
        raise HTTPException(404) from None
    info = await session.info()
    if info.metadata.get("user_id") != current_user(request):
        raise HTTPException(404)
    return session


@app.get("/")
async def index():
    return FileResponse(Path(__file__).with_name("index.html"))


@app.post("/sessions")
async def create_session(request: HttpRequest):
    session = await request.app.state.runner.new_session(metadata={"user_id": current_user(request)})
    return {"session_id": session.id}


class MessageIn(BaseModel):
    text: str


@app.post("/sessions/{session_id}/messages")
async def post_message(request: HttpRequest, session_id: str, body: MessageIn):
    session = await open_session(request, session_id)
    try:
        await session.send(body.text).queued()
    except SessionClosed:
        raise HTTPException(409, "会话已关闭") from None
    return {"ok": True}


@app.get("/sessions/{session_id}/events")
async def stream_events(request: HttpRequest, session_id: str):
    session = await open_session(request, session_id)
    after = int(request.headers.get("last-event-id", 0))

    async def generate():
        async for event in session.events(after=after, snapshot=True, children=True):
            data = json.dumps(event.to_dict(), ensure_ascii=False)
            # seq 按会话编号，只有顶层会话的事件可以作为 SSE 的 id，用于断线重连
            if event.session_id == session.id and event.seq is not None:
                yield f"id: {event.seq}\ndata: {data}\n\n"
            else:
                yield f"data: {data}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


class AnswerIn(BaseModel):
    value: Any


@app.post("/sessions/{session_id}/requests/{request_id}")
async def answer_request(request: HttpRequest, session_id: str, request_id: str, body: AnswerIn):
    session = await open_session(request, session_id)
    try:
        await session.answer(request_id, body.value).queued()
    except InvalidAnswer as error:
        raise HTTPException(400, str(error)) from None
    except (RequestClosed, SessionClosed):
        raise HTTPException(409, "请求已不在等待答复") from None
    return {"ok": True}


@app.post("/sessions/{session_id}/stop")
async def stop(request: HttpRequest, session_id: str):
    session = await open_session(request, session_id)
    await session.stop()
    return {"ok": True}


@app.post("/sessions/{session_id}/close")
async def close(request: HttpRequest, session_id: str):
    session = await open_session(request, session_id)
    await session.close()
    return {"ok": True}
