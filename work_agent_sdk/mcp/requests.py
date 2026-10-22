from __future__ import annotations

from pydantic import BaseModel

from work_agent_sdk.core.requests import Request


class Authorization(Request, answered_by="backend"):
    """MCP 授权请求：前端打开 url；授权回调到达后由 MCPService 答复（answered_by="backend"）。"""

    server: str
    url: str

    class Answer(BaseModel):
        ok: bool
        error: str = ""
