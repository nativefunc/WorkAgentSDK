import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from work_agent_sdk import MCP, Agent, MCPService, OAuth, Runner
from work_agent_sdk.events import TurnEnded
from work_agent_sdk.models import OpenAI

tracker = MCP(
    "tracker",
    url=os.environ["TRACKER_MCP_URL"],
    auth=OAuth(redirect_uri="http://127.0.0.1:8000/oauth/callback", scopes=["read"]),
)

agent = Agent(
    "assistant",
    model=OpenAI("gpt-5"),
    instructions="You are an assistant who helps the user manage their to-do list.",
    tools=[tracker],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with Runner(agents=[agent], secret_key="${WORK_AGENT_SECRET_KEY}") as runner:
        app.state.runner = runner
        app.state.session = await runner.new_session()
        app.state.waiting_turn = None
        yield


app = FastAPI(lifespan=lifespan)


@app.get("/ask", response_class=HTMLResponse)
async def ask(text: str):
    result = await app.state.session.send(text)
    for request in result.pending:
        if request.type == "Authorization":
            app.state.waiting_turn = result.turn_id
            return f'<a href="{request.data["url"]}">Authorize {request.data["server"]}</a>'
    return result.text


@app.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(state: str, code: str | None = None, error: str | None = None):
    outcome = await app.state.runner.service(MCPService).complete_authorization(
        state=state,
        code=code,
        error=error,
    )
    if not outcome.ok:
        return f"Authorization failed: {outcome.error}"

    async for event in app.state.session.events():
        if (
            isinstance(event, TurnEnded)
            and event.turn_id == app.state.waiting_turn
            and event.result.status != "waiting"
        ):
            return event.result.text


@app.post("/oauth/revoke")
async def revoke():
    return {"revoked": await app.state.runner.service(MCPService).revoke("tracker")}
