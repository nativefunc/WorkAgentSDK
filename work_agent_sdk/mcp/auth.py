from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel

from work_agent_sdk.mcp.config import MCPServer
from work_agent_sdk.mcp.connection import ConnectionPool, guard_requests
from work_agent_sdk.mcp.oauth import (
    AuthRequired,
    build_provider,
    find_error,
    revoke_tokens,
)

# When authorization completes, answer the requests in sessions waiting for this server's authorization (provided by the runtime). Arguments: session, server name, success, failure reason
AnswerAuthorization = Callable[[str, str, bool, str | None], Awaitable[None]]
# MCP servers registered on the current Runner, keyed by name
ServerList = Callable[[], dict[str, MCPServer]]

logger = logging.getLogger("work_agent_sdk")


class AuthorizationResult(BaseModel):
    ok: bool
    server: str
    error: str | None = None


class _PendingAuthorization:
    def __init__(self, server: MCPServer) -> None:
        loop = asyncio.get_running_loop()
        self.server = server
        self.oauth, self.url = server.oauth_target()
        self.waiting_sessions: set[str] = set()
        self.authorization_url: asyncio.Future = loop.create_future()
        self.callback: asyncio.Future = loop.create_future()

        # Set by AuthManager.start right after creation
        self.task: asyncio.Task[None]
        self.created_at = time.time()


class AuthManager:
    def __init__(self, pool: ConnectionPool, servers: ServerList, answer: AnswerAuthorization) -> None:
        self.pool = pool
        self._servers = servers
        self._answer = answer
        self._pending: dict[str, _PendingAuthorization] = {}
        self._background: set[asyncio.Task] = set()

    def find_server(self, name: str) -> MCPServer:
        server = self._servers().get(name)
        if server is None:
            raise LookupError(f"MCP server {name} does not exist")
        return server

    async def start(self, server: MCPServer, session_id: str | None = None) -> str:
        await self._expire()

        for pending in self._pending.values():
            if pending.server.name == server.name and not pending.callback.done():
                if session_id:
                    pending.waiting_sessions.add(session_id)
                return pending.authorization_url.result()

        pending = _PendingAuthorization(server)
        if session_id:
            pending.waiting_sessions.add(session_id)

        storage = self.pool.token_storage(server, hide_tokens=True)
        known = pending.oauth.known_client()
        if known is not None and await storage.get_client_info() is None:
            await storage.set_client_info(known)

        pending.task = asyncio.create_task(self._run_flow(pending))
        await asyncio.wait(
            {pending.authorization_url, pending.task},
            timeout=server.timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if not pending.authorization_url.done():
            pending.task.cancel()
            await asyncio.gather(pending.task, return_exceptions=True)
            error = None if pending.task.cancelled() else pending.task.exception()
            reason = find_error(error, AuthRequired) or error or "the authorization server didn't respond"
            raise AuthRequired(f"Can't start authorization for {server.name}: {reason}")

        url = pending.authorization_url.result()
        state = (parse_qs(urlparse(url).query).get("state") or [""])[0]
        self._pending[state] = pending
        pending.task.add_done_callback(lambda task: self._flow_ended(state, task))
        return url

    async def _run_flow(self, pending: _PendingAuthorization) -> None:
        from mcp import Client
        from mcp.client.streamable_http import (
            create_mcp_http_client,
            streamable_http_client,
        )
        from mcp.shared.auth import AuthorizationCodeResult

        server = pending.server
        storage = self.pool.token_storage(server, hide_tokens=True)

        async def redirect_handler(url: str) -> None:
            pending.oauth.check_authorization_url(server.name, pending.url, url)
            if not pending.authorization_url.done():
                pending.authorization_url.set_result(url)

        async def callback_handler() -> Any:
            code, state = await pending.callback
            return AuthorizationCodeResult(code=code, state=state)

        provider = build_provider(
            pending.oauth,
            server.name,
            pending.url,
            storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )
        async with create_mcp_http_client(auth=provider) as http:
            guard_requests(http, server)
            async with Client(streamable_http_client(pending.url, http_client=http)) as client:
                await client.list_tools()

    async def complete(self, *, state: str, code: str | None = None, error: str | None = None) -> AuthorizationResult:
        await self._expire()
        pending = self._pending.pop(state, None)
        if pending is None:
            raise LookupError("The authorization request doesn't exist or has expired; start authorization again")

        failure: str | None
        if error or not code:
            pending.task.cancel()
            failure = f"The user didn't grant authorization ({error})" if error else "The authorization callback is missing code"
        else:
            pending.callback.set_result((code, state))

            try:
                await asyncio.wait_for(asyncio.shield(pending.task), timeout=60)
                failure = None
            except TimeoutError:
                pending.task.cancel()
                failure = "Timed out exchanging the token"
            except Exception as flow_error:
                failure = f"Failed to exchange the token: {find_error(flow_error, AuthRequired) or flow_error}"

        if failure is None:
            await self.pool.disconnect_server(pending.server.name)

        await self._deliver(pending, failure)
        return AuthorizationResult(ok=failure is None, server=pending.server.name, error=failure)

    async def _deliver(self, pending: _PendingAuthorization, failure: str | None) -> None:
        for session_id in pending.waiting_sessions:
            with contextlib.suppress(LookupError):
                await self._answer(session_id, pending.server.name, failure is None, failure)

    def _flow_ended(self, state: str, task: asyncio.Task) -> None:
        pending = self._pending.get(state)
        if pending is None or pending.callback.done():
            return

        self._pending.pop(state, None)
        failure = "The authorization flow was interrupted" if task.cancelled() else f"Authorization failed: {task.exception()}"
        task = asyncio.create_task(self._deliver(pending, failure))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _expire(self) -> None:
        moment = time.time()
        for state, pending in list(self._pending.items()):
            if moment - pending.created_at < pending.oauth.state_ttl:
                continue

            self._pending.pop(state, None)
            pending.task.cancel()
            await self._deliver(pending, "Authorization timed out; the user didn't complete it")

    async def authorize_url(self, server_name: str) -> str:
        server = self.find_server(server_name)
        if server.auth is None:
            raise ValueError(f"MCP server {server_name} has no OAuth configured")
        return await self.start(server)

    async def status(self, server_name: str) -> dict[str, Any]:
        server = self.find_server(server_name)
        if server.auth is None:
            return {"server": server_name, "status": "not_needed"}

        authorized = await self.pool.token_storage(server).has_tokens()
        return {"server": server_name, "status": "authorized" if authorized else "required"}

    async def revoke(self, server_name: str) -> bool:
        server = self.find_server(server_name)
        storage = self.pool.token_storage(server)
        revoked = await revoke_tokens(*server.oauth_target(), storage) if server.auth else False
        await storage.clear()
        await self.pool.disconnect_server(server_name)
        return revoked

    async def close(self) -> None:
        for pending in self._pending.values():
            if pending.task is not None:
                pending.task.cancel()

        self._pending.clear()

        for task in list(self._background):
            task.cancel()

        await asyncio.gather(*self._background, return_exceptions=True)
