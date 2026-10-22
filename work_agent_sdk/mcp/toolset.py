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
    """MCP 服务工具集，参数与 MCPServer 相同，例如 MCP("github", url=..., auth=OAuth(...))。"""

    needs = (MCPService,)

    def __init__(self, name: str, **options: Any) -> None:
        super().__init__(name)
        self.server = MCPServer(name, **options)
        self.description = self.server.description

    def __repr__(self) -> str:
        return f"MCP({self.name!r})"

    async def tools(self, context: Context) -> list[Tool]:
        server = self.server
        # 在工作区中启动的服务需要会话有工作区；没有时不提供该服务的工具，而不是让这一轮失败
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
            logger.warning("MCP 服务 %s 暂不可用：%s", server.name, error)
            return []

        if connection.tools_changed:
            await pool.refresh_tools(server, connection)

        tools: list[Tool] = []
        seen: dict[str, str] = {}
        for meta in connection.tools:
            name = re.sub(r"[^A-Za-z0-9_\-]", "_", f"mcp__{server.name}__{meta.name}")[:64]
            if name in seen:
                logger.error("MCP 服务 %s 的工具 %r 与 %r 截断后同名，已跳过后者", server.name, seen[name], meta.name)
                continue

            seen[name] = meta.name
            tools.append(MCPTool(server, meta, name))

        if server.resources:
            tools += [ListResourcesTool(server), ReadResourceTool(server)]

        return tools


__all__ = ["MCP", "OAuth"]
