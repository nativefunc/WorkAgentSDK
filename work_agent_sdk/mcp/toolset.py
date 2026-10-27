from __future__ import annotations

import logging
import re
from typing import Any

from work_agent_sdk.core.tool import Context, Tool, Toolset
from work_agent_sdk.mcp.config import MCPServer
from work_agent_sdk.mcp.oauth import AuthRequired, OAuth
from work_agent_sdk.mcp.service import MCPService
from work_agent_sdk.mcp.tools import (
    ConnectTool,
    ListResourcesTool,
    MCPTool,
    ReadResourceTool,
    connection_scope,
)

logger = logging.getLogger("work_agent_sdk")


class MCP(Toolset):
    """Connects to an MCP server and offers its tools to the model, e.g. MCP("github", url=..., auth=OAuth(...))."""

    needs = (MCPService,)

    def __init__(self, name: str, **options: Any) -> None:
        super().__init__(name)
        self.server = MCPServer(name, **options)
        self.description = self.server.description

    def __repr__(self) -> str:
        return f"MCP({self.name!r})"

    async def tools(self, context: Context) -> list[Tool]:
        server = self.server
        # Servers started in the workspace need the session to have a workspace; without one, this server's tools aren't offered, rather than failing the turn
        if server.runs_on == "workspace" and not context.has_resource("workspace"):
            return []

        pool = context.service(MCPService).pool
        if not await pool.authorized(server):
            return [ConnectTool(server)]

        try:
            connection = await pool.connection(server, await connection_scope(context, server))
        except AuthRequired:
            return [ConnectTool(server)]
        except ConnectionError as error:
            logger.warning("MCP server %s is temporarily unavailable: %s", server.name, error)
            return []

        if connection.tools_changed:
            await pool.refresh_tools(server, connection)

        tools: list[Tool] = []
        seen: dict[str, str] = {}
        for meta in connection.tools:
            name = re.sub(r"[^A-Za-z0-9_\-]", "_", f"mcp__{server.name}__{meta.name}")[:64]
            if name in seen:
                logger.error("Tools %r and %r of MCP server %s have the same name after truncation; skipping the latter", seen[name], meta.name, server.name)
                continue

            seen[name] = meta.name
            tools.append(MCPTool(server, meta, name))

        if server.resources:
            tools += [ListResourcesTool(server), ReadResourceTool(server)]

        return tools


__all__ = ["MCP", "OAuth"]
