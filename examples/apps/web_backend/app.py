import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
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
from work_agent_sdk.models import OpenAI


@tool(description="Refund an order")
async def refund(ctx, order_id: str, amount: float) -> str:
    answer = await ctx.wait_for(Approval(title=f"Refund {amount} yuan for order {order_id}?"))
    return f"Refunded {amount} yuan for order {order_id}" if answer.approved else "The user denied the refund"


agent = Agent(
    "support",
    model=OpenAI("gpt-5"),
    instructions="You are an online store's customer service agent and can process refunds.",
    tools=[refund],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with Runner(agents=[agent]) as runner:
        app.state.runner = runner
        yield


app = FastAPI(lifespan=lifespan)


class MessageIn(BaseModel):
    text: str


class AnswerIn(BaseModel):
    value: Any


async def open_session(session_id: str, user: str):
    try:
        session = await app.state.runner.session(session_id)
    except KeyError:
        raise HTTPException(404) from None
    info = await session.info()
    if info.metadata.get("user_id") != user:
        raise HTTPException(404)
    return session


@app.get("/")
async def index():
    return FileResponse(Path(__file__).with_name("index.html"))


@app.post("/sessions")
async def create_session(user: str):
    session = await app.state.runner.new_session(metadata={"user_id": user})
    return {"session_id": session.id}


@app.post("/sessions/{session_id}/messages")
async def post_message(session_id: str, user: str, body: MessageIn):
    session = await open_session(session_id, user)
    try:
        await session.send(body.text).queued()
    except SessionClosed:
        raise HTTPException(409, "Session is closed") from None
    return {"ok": True}


@app.get("/sessions/{session_id}/events")
async def stream_events(request: Request, session_id: str, user: str):
    session = await open_session(session_id, user)
    after = int(request.headers.get("last-event-id", 0))

    async def generate():
        async for event in session.events(after=after, snapshot=True, children=True):
            data = json.dumps(event.to_dict(), ensure_ascii=False)
            if event.session_id == session.id and event.seq is not None:
                yield f"id: {event.seq}\ndata: {data}\n\n"
            else:
                yield f"data: {data}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/sessions/{session_id}/requests/{request_id}")
async def answer_request(session_id: str, request_id: str, user: str, body: AnswerIn):
    session = await open_session(session_id, user)
    try:
        await session.answer(request_id, body.value).queued()
    except InvalidAnswer as error:
        raise HTTPException(400, str(error)) from None
    except (RequestClosed, SessionClosed):
        raise HTTPException(409, "Request is no longer awaiting an answer") from None
    return {"ok": True}


@app.post("/sessions/{session_id}/stop")
async def stop_session(session_id: str, user: str):
    session = await open_session(session_id, user)
    await session.stop()
    return {"ok": True}


@app.post("/sessions/{session_id}/close")
async def close_session(session_id: str, user: str):
    session = await open_session(session_id, user)
    await session.close()
    return {"ok": True}
