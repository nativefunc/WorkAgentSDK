from __future__ import annotations

import asyncio
import contextlib
import logging
import shlex
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from work_agent_sdk.host.commands.run import Command
from work_agent_sdk.mcp.config import MCPServer
from work_agent_sdk.mcp.oauth import (
    AuthRequired,
    TokenRecords,
    TokenStorage,
    build_provider,
    find_error,
    origin_of,
)
from work_agent_sdk.nodes.base import Node

logger = logging.getLogger("work_agent_sdk")

MAX_PAGES = 1000
RETRY_AFTER = 30

# How runs_on="workspace" servers are launched: (command line, environment variables) -> (executor, command that doesn't enter the sandbox)
Launch = Callable[[str, dict[str, str]], tuple[Node, Command]]


@dataclass(frozen=True)
class ConnectionScope:
    session_id: str
    launch: Launch | None = None


class Connection:
    def __init__(self) -> None:
        self.client: Any = None
        self.tools: list[Any] = []
        self.tools_changed = False
        self.ready = asyncio.Event()
        self.closing = asyncio.Event()
        self.task: asyncio.Task | None = None
        self.error: BaseException | None = None

    @property
    def alive(self) -> bool:
        return self.client is not None and self.task is not None and not self.task.done()

    async def close(self) -> None:
        self.closing.set()
        if self.task is not None:
            await asyncio.gather(self.task, return_exceptions=True)

    async def handle_message(self, message: Any) -> None:
        root = getattr(message, "root", message)
        if (
            type(root).__name__ == "ToolListChangedNotification"
            or getattr(root, "method", "") == "notifications/tools/list_changed"
        ):
            self.tools_changed = True


async def list_all_pages(fetch: Callable[..., Awaitable[Any]], field: str) -> list[Any]:
    items: list[Any] = []
    cursor = None
    for _ in range(MAX_PAGES):
        page = await fetch(cursor=cursor) if cursor else await fetch()
        items.extend(getattr(page, field) or [])
        cursor = getattr(page, "next_cursor", None) or getattr(page, "nextCursor", None)
        if not cursor:
            break

    return items


def is_connection_closed(error: BaseException) -> bool:
    import anyio

    if find_error(error, (anyio.ClosedResourceError, anyio.BrokenResourceError, anyio.EndOfStream)) is not None:
        return True

    try:
        from mcp.shared.exceptions import MCPError
        from mcp.types import CONNECTION_CLOSED
    except ImportError:
        return False

    mcp_error = find_error(error, MCPError)
    return mcp_error is not None and getattr(mcp_error, "code", None) == CONNECTION_CLOSED


def is_auth_error(error: BaseException) -> bool:
    if find_error(error, AuthRequired) is not None:
        return True
    try:
        from mcp.client.auth import OAuthFlowError
    except ImportError:
        return False
    return find_error(error, OAuthFlowError) is not None


@contextlib.asynccontextmanager
async def workspace_stdio(node: Node, spec: Command, label: str = "") -> AsyncIterator[tuple[Any, Any]]:
    import anyio
    from mcp.client.stdio import _parse_line

    read_sender, read_receiver = anyio.create_memory_object_stream(0)
    write_sender, write_receiver = anyio.create_memory_object_stream(0)
    stdin: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def stdin_chunks() -> AsyncIterator[bytes]:
        while True:
            piece = await stdin.get()
            if piece is None:
                return
            yield piece

    async def read_messages() -> None:
        pending = b""
        stderr = bytearray()
        exit_code: int | None = None
        async with read_sender:
            async for chunk in node.exec(spec, stdin_chunks()):
                if chunk.stream == "stdout":
                    *lines, pending = (pending + chunk.data).split(b"\n")
                    for line in lines:
                        if line.strip():
                            await read_sender.send(_parse_line(line.decode("utf-8", errors="replace")))
                elif chunk.stream == "stderr":
                    stderr += chunk.data
                    logger.debug("MCP stderr: %s", chunk.data.decode(errors="replace").rstrip())
                elif chunk.stream == "exit":
                    exit_code = chunk.code

        if exit_code not in (0, None):
            detail = stderr.decode(errors="replace").strip() or "no output"
            raise RuntimeError(f"MCP server {label} in the workspace failed to start (exit code {exit_code}): {detail[:500]}")

    async def write_messages() -> None:
        async with write_receiver:
            async for session_message in write_receiver:
                line = session_message.message.model_dump_json(by_alias=True, exclude_unset=True) + "\n"
                await stdin.put(line.encode())
        await stdin.put(None)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(read_messages)
        task_group.start_soon(write_messages)
        try:
            yield read_receiver, write_sender
        finally:
            await stdin.put(None)
            task_group.cancel_scope.cancel()


class ConnectionPool:
    def __init__(self, tokens: TokenRecords) -> None:
        self.tokens = tokens
        self._connections: dict[str, Connection] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._failures: dict[str, tuple[float, str]] = {}

    def token_storage(self, server: MCPServer, *, hide_tokens: bool = False) -> TokenStorage:
        return TokenStorage(self.tokens, server.name, server.url or "", hide_tokens=hide_tokens)

    def problem(self, server_name: str) -> str | None:
        for key, (_, message) in self._failures.items():
            if key.split("\n", 1)[0] == server_name:
                return message
        return None

    async def authorized(self, server: MCPServer) -> bool:
        return server.auth is None or await self.token_storage(server).has_tokens()

    def connection_key(self, server: MCPServer, scope: ConnectionScope) -> str:
        config = server.connection_config()
        if server.runs_on == "workspace":
            if scope.launch is None:
                raise ConnectionError(f"MCP server {server.name} must run on the node the workspace is on, but this session has no workspace configured")
            # Servers started in the workspace use the session's working directory and environment variables and aren't shared with other sessions
            return f"{server.name}\n{config}\n{scope.session_id}"
        return f"{server.name}\n{config}"

    async def connection(self, server: MCPServer, scope: ConnectionScope) -> Connection:
        if not await self.authorized(server):
            raise AuthRequired(f"{server.name} requires user authorization")

        key = self.connection_key(server, scope)
        connection = self._connections.get(key)
        if connection is not None and connection.alive:
            return connection

        async with self._locks.setdefault(key, asyncio.Lock()):
            connection = self._connections.get(key)
            if connection is not None and connection.alive:
                return connection
            if connection is not None:
                await connection.close()

            connection = await self._open(key, server, scope)
            self._connections[key] = connection
            return connection

    async def _open(self, key: str, server: MCPServer, scope: ConnectionScope) -> Connection:
        loop = asyncio.get_running_loop()
        failure = self._failures.get(key)
        if failure is not None and loop.time() - failure[0] < RETRY_AFTER:
            raise ConnectionError(failure[1])

        connection = Connection()
        connection.task = asyncio.create_task(self._keep_connected(connection, server, scope))
        try:
            await asyncio.wait_for(connection.ready.wait(), timeout=server.timeout)
        except TimeoutError:
            connection.task.cancel()
            await asyncio.gather(connection.task, return_exceptions=True)
            message = f"Timed out connecting to MCP server {server.name} ({server.timeout:g} seconds)"
            self._failures[key] = (loop.time(), message)
            raise ConnectionError(message) from None

        if connection.error is not None:
            if is_auth_error(connection.error):
                await self.token_storage(server).forget_tokens()
                raise AuthRequired(f"Authorization for {server.name} has expired; the user needs to authorize again") from connection.error

            message = f"Failed to connect to MCP server {server.name}: {connection.error}"
            self._failures[key] = (loop.time(), message)
            raise ConnectionError(message) from connection.error

        self._failures.pop(key, None)
        return connection

    async def _keep_connected(self, connection: Connection, server: MCPServer, scope: ConnectionScope) -> None:
        from mcp import Client

        try:
            async with contextlib.AsyncExitStack() as stack:
                transport = await self._transport(server, scope, stack)
                async with Client(transport, message_handler=connection.handle_message) as client:
                    connection.client = client
                    connection.tools = await list_all_pages(client.list_tools, "tools")
                    connection.ready.set()
                    await connection.closing.wait()
        except BaseException as error:
            if connection.ready.is_set() and not isinstance(error, asyncio.CancelledError):
                # Failures while connecting are reported by the caller; here we only log established connections that drop midway
                logger.warning("Connection to MCP server %s dropped: %s", server.name, error)
            connection.error = error
            connection.ready.set()
        finally:
            connection.client = None

    async def _transport(self, server: MCPServer, scope: ConnectionScope, stack: contextlib.AsyncExitStack) -> Any:
        if server.url:
            from mcp.client.streamable_http import (
                create_mcp_http_client,
                streamable_http_client,
            )

            auth = self._oauth_provider(server) if server.auth is not None else None
            http = await stack.enter_async_context(create_mcp_http_client(auth=auth))
            guard_requests(http, server)
            return streamable_http_client(server.url, http_client=http)

        if server.command is None:
            raise ValueError(f"MCP server {server.name} has neither url nor command configured")

        env = server.resolved_env()
        if server.runs_on == "workspace":
            command = shlex.join([server.command, *server.args])
            assert scope.launch is not None
            return workspace_stdio(*scope.launch(command, env), label=server.name)

        from mcp import StdioServerParameters

        return StdioServerParameters(command=server.command, args=server.args, env=env or None)

    def _oauth_provider(self, server: MCPServer) -> Any:
        storage = self.token_storage(server)

        async def redirect_handler(url: str) -> None:
            await storage.forget_tokens()
            raise AuthRequired(f"{server.name} requires user authorization")

        async def callback_handler() -> Any:
            raise AuthRequired(f"{server.name} requires user authorization")

        oauth, url = server.oauth_target()
        return build_provider(
            oauth,
            server.name,
            url,
            storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

    async def request(self, server: MCPServer, scope: ConnectionScope, send: Callable[[Any], Awaitable[Any]]) -> Any:
        # If the connection drops mid-call the result is unknown, so don't retry
        connection = await self.connection(server, scope)
        if not connection.alive:
            await self.close_connection(server, scope)
            connection = await self.connection(server, scope)

        try:
            return await send(connection.client)
        except Exception as error:
            if is_connection_closed(error) or not connection.alive:
                await self.close_connection(server, scope)
                raise ConnectionError(f"The connection to MCP server {server.name} dropped; the result of this call is unknown") from error
            raise

    async def refresh_tools(self, server: MCPServer, connection: Connection) -> None:
        connection.tools_changed = False
        try:
            connection.tools = await list_all_pages(connection.client.list_tools, "tools")
        except Exception:
            logger.exception("MCP server %s failed to refresh its tool list", server.name)

    async def close_connection(self, server: MCPServer, scope: ConnectionScope) -> None:
        key = self.connection_key(server, scope)
        connection = self._connections.pop(key, None)
        if connection is not None:
            await connection.close()

    async def disconnect_server(self, name: str) -> None:
        for key, connection in list(self._connections.items()):
            if key.split("\n", 1)[0] == name:
                self._connections.pop(key, None)
                self._failures.pop(key, None)
                await connection.close()

    async def close_session(self, session_id: str) -> None:
        for key, connection in list(self._connections.items()):
            if key.endswith(f"\n{session_id}"):
                self._connections.pop(key, None)
                self._failures.pop(key, None)
                await connection.close()

    async def close(self) -> None:
        for connection in list(self._connections.values()):
            await connection.close()
        self._connections.clear()


def guard_requests(http: Any, server: MCPServer) -> None:
    # Configured headers are only sent to the server's own address and don't leak through redirects or authorization requests
    headers = server.resolved_headers()
    server_origin = origin_of(server.url or "")

    async def before_request(request: Any) -> None:
        url = str(request.url)
        if origin_of(url) == server_origin:
            request.headers.update(headers)
        else:
            # When redirected to another site, remove custom headers copied from the previous request
            for name in headers:
                request.headers.pop(name, None)

    http.event_hooks["request"].append(before_request)
