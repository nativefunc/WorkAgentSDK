"""MCP OAuth 授权：MCP 服务需要用户登录授权时，模型发出授权请求，用户在浏览器中完成授权，后端在回调中完成授权。

OAuth 令牌按服务保存，Runner 中所有会话共用同一份。

运行：
    pip install fastapi uvicorn cryptography
    export WORK_AGENT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
    export TRACKER_MCP_URL=https://mcp.tracker.example.com/mcp
    uvicorn app:app --port 8000
    然后打开 http://127.0.0.1:8000/ask?text=列出我的待办
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from work_agent_sdk import MCP, Agent, MCPService, OAuth, Runner
from work_agent_sdk.models import Claude

tracker = MCP(
    "tracker",
    url=os.environ["TRACKER_MCP_URL"],
    auth=OAuth(redirect_uri="http://127.0.0.1:8000/oauth/callback", scopes=["read"]),
)

agent = Agent("assistant", model=Claude("claude-sonnet-4-5"), tools=[tracker])


@asynccontextmanager
async def lifespan(app: FastAPI):
    # secret_key 用于加密保存 OAuth 令牌；不配置时令牌只保存在内存中，重启后需要重新授权
    async with Runner(agents=[agent], secret_key="${WORK_AGENT_SECRET_KEY}") as runner:
        app.state.runner = runner
        app.state.session = await runner.new_session()
        yield


app = FastAPI(lifespan=lifespan)


@app.get("/ask", response_class=HTMLResponse)
async def ask(text: str):
    session = app.state.session
    result = await session.send(text)
    for request in result.pending:
        # 尚未授权时，模型调用 connect_tracker 工具，框架发出 Authorization 请求
        if request.type == "Authorization":
            return f'<a href="{request.data["url"]}" target="_blank">授权 tracker</a>，完成后刷新本页'
    return result.text


@app.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(state: str, code: str | None = None, error: str | None = None):
    # 框架换取并保存令牌，答复等待中的 Authorization 请求，这一轮继续执行
    await app.state.runner.service(MCPService).complete_authorization(state=state, code=code, error=error)
    return "授权完成，可以关闭此页"


@app.post("/oauth/revoke")
async def revoke():
    return {"revoked": await app.state.runner.service(MCPService).revoke("tracker")}
