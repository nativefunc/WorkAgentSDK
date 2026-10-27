from __future__ import annotations

from pydantic import BaseModel

from work_agent_sdk.core.requests import Request


class Authorization(Request, answered_by="backend"):
    """MCP authorization request: the frontend opens url; once the authorization callback arrives, MCPService answers it (answered_by="backend")."""

    server: str
    url: str

    class Answer(BaseModel):
        ok: bool
        error: str = ""
