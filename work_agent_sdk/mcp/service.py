from __future__ import annotations

import contextlib
from typing import Any

from work_agent_sdk.core.errors import RequestClosed
from work_agent_sdk.core.service import RunnerAPI, Service, SessionRef
from work_agent_sdk.core.tool import Toolset, unwrap
from work_agent_sdk.mcp.auth import AuthManager, AuthorizationResult
from work_agent_sdk.mcp.config import MCPServer
from work_agent_sdk.mcp.connection import ConnectionPool
from work_agent_sdk.mcp.oauth import TokenRecords
from work_agent_sdk.mcp.store import MCPTokenStore, SqliteMCPTokenStore


class MCPService(Service):
    """token_store is the token storage; uses data_dir/ext/mcp/mcp.db when omitted."""

    def __init__(self, *, token_store: MCPTokenStore | None = None) -> None:
        self._servers: dict[str, MCPServer] = {}
        self.token_store = token_store

    def __repr__(self) -> str:
        return f"MCPService(servers={list(self._servers)})"

    async def attach(self, api: RunnerAPI) -> None:
        await super().attach(api)

        if self.token_store is None:
            self.token_store = SqliteMCPTokenStore(api.files("mcp") / "mcp.db")

        self.pool = ConnectionPool(TokenRecords(self.token_store, api.secret_key))
        self.auth = AuthManager(self.pool, self.registered, self._answer)

    async def _answer(self, session_id: str, server: str, ok: bool, error: str | None) -> None:
        for request in await self.api.pending(session_id):
            if request.type == "Authorization" and request.data.get("server") == server:
                with contextlib.suppress(RequestClosed):
                    await self.api.answer(request.session_id, request.id, {"ok": ok, "error": error or ""})

    def register(self, server: MCPServer) -> None:
        self._servers[server.name] = server

    def registered(self) -> dict[str, MCPServer]:
        return dict(self._servers)

    def servers(self) -> list[dict[str, Any]]:
        return [
            {
                "server": name,
                "url": server.url,
                "command": server.command,
                "oauth": server.auth is not None,
            }
            for name, server in self._servers.items()
        ]

    async def status(self, server: str) -> dict[str, Any]:
        return await self.auth.status(server)

    async def authorize_url(self, server: str) -> str:
        """Start authorization outside a session and return the authorization page URL. Existing tokens are kept until a new token is obtained."""
        return await self.auth.authorize_url(server)

    async def complete_authorization(
        self, *, state: str, code: str | None = None, error: str | None = None
    ) -> AuthorizationResult:
        """Handle the authorization callback: exchange and save the token, and answer the requests in sessions waiting for this authorization."""
        return await self.auth.complete(state=state, code=code, error=error)

    async def revoke(self, server: str) -> bool:
        """Ask the authorization server to revoke the token (when supported), delete the saved token and disconnect; returns whether the authorization server confirmed the revocation."""
        return await self.auth.revoke(server)

    async def disconnect(self, server: str) -> None:
        """Disconnect from this server; reconnects on next use."""
        await self.pool.disconnect_server(server)

    async def toolset_added(self, toolset: Toolset) -> None:
        server = getattr(unwrap(toolset), "server", None)
        if isinstance(server, MCPServer):
            self.register(server)

    async def toolset_removed(self, toolset: Toolset) -> None:
        server = getattr(unwrap(toolset), "server", None)
        if isinstance(server, MCPServer):
            self._servers.pop(server.name, None)
            await self.pool.disconnect_server(server.name)

    async def session_closing(self, session: SessionRef) -> None:
        """Shut down the servers started in the workspace for this session."""
        await self.pool.close_session(session.id)

    async def runner_stopped(self) -> None:
        await self.auth.close()
        await self.pool.close()
        if self.token_store is not None:
            await self.token_store.close()
