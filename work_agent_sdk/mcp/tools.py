from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

import work_agent_sdk.strings.mcp as strings
from work_agent_sdk.core.errors import ToolError
from work_agent_sdk.core.messages import MediaPart, TextPart, ToolResult
from work_agent_sdk.core.tool import Context, Tool
from work_agent_sdk.core.untrusted import wrap_external
from work_agent_sdk.host.commands.run import Command
from work_agent_sdk.mcp.config import MCPServer
from work_agent_sdk.mcp.connection import ConnectionScope, list_all_pages
from work_agent_sdk.mcp.oauth import AuthRequired
from work_agent_sdk.mcp.requests import Authorization
from work_agent_sdk.mcp.service import MCPService
from work_agent_sdk.workspace.service import BoundWorkspace

MAX_UNKNOWN_BLOCK_CHARS = 20_000
MAX_AUDIO_BYTES = 20_000_000


def server_hints(meta: Any) -> dict[str, Any]:
    annotations = getattr(meta, "annotations", None)
    if annotations is None:
        return {}

    data = (
        annotations.model_dump(exclude_none=True, by_alias=True)
        if hasattr(annotations, "model_dump")
        else dict(annotations)
    )
    hints = {}
    for key, value in data.items():
        snake_case = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
        hints[snake_case.removesuffix("_hint")] = value

    return hints


async def connection_scope(context: Context, server: MCPServer) -> ConnectionScope:
    if server.runs_on != "workspace":
        return ConnectionScope(context.session_id)

    workspace: BoundWorkspace | None = await context.resource("workspace")
    if workspace is None:
        raise ToolError(f"MCP 服务 {server.name} 需要在工作区中启动，但当前会话未配置工作区", code="no_workspace")

    def launch(line: str, env: dict[str, str]) -> tuple[Any, Command]:
        # MCPServer.env 是服务自身的配置：用沙箱时经命令私有文件在沙箱内传入，不进入沙箱外的启动程序
        command = workspace.command(line, unsandboxed=server.unsandboxed)
        return workspace.node, Command.model_validate({**command.model_dump(), "env": env})

    return ConnectionScope(context.session_id, launch)


def to_tool_result(response: Any, source: str) -> ToolResult:
    parts: list[Any] = []
    for block in response.content or []:
        kind = getattr(block, "type", None)
        if kind == "text":
            parts.append(TextPart(text=wrap_external(source, block.text)))
        elif kind == "image":
            # 原样写入记录；超过模型上限的图片在写入记录时替换为文字说明
            mime = getattr(block, "mime_type", None) or getattr(block, "mimeType", None) or "image/png"
            parts.append(MediaPart(kind="image", mime=mime, data=block.data))
        elif kind == "audio":
            if len(block.data) * 3 // 4 > MAX_AUDIO_BYTES:
                parts.append(TextPart(text=strings.AUDIO_TOO_LARGE.format(limit=MAX_AUDIO_BYTES // 1_000_000)))
                continue
            mime = getattr(block, "mime_type", None) or getattr(block, "mimeType", None) or "audio/wav"
            parts.append(MediaPart(kind=kind, mime=mime, data=block.data))
        else:
            text = json.dumps(block.model_dump(mode="json"), ensure_ascii=False)
            parts.append(TextPart(text=wrap_external(source, text[:MAX_UNKNOWN_BLOCK_CHARS])))

    structured = getattr(response, "structured_content", None) or getattr(response, "structuredContent", None)
    if getattr(response, "is_error", None) or getattr(response, "isError", None):
        text = "".join(part.text for part in parts if isinstance(part, TextPart)) or strings.TOOL_ERROR
        return ToolResult(content=parts, data=structured, error=text, error_code="mcp_error")
    return ToolResult(content=parts, data=structured)


async def authorize(context: Context, server: MCPServer) -> None:
    if server.auth is None:
        raise ToolError(f"{server.name} 需要授权，但未配置 OAuth", code="auth_required")

    auth = context.service(MCPService).auth
    url = await context.step(f"authorize:{server.name}", lambda: auth.start(server, context.session_id))
    answer = await context.wait_for(Authorization(server=server.name, url=url))
    if not answer.ok:
        raise ToolError(f"{server.name} 的授权未完成：{answer.error}", code="auth_failed")


async def call_server(context: Context, server: MCPServer, send: Callable[[Any], Awaitable[Any]]) -> Any:
    pool = context.service(MCPService).pool
    scope = await connection_scope(context, server)
    try:
        return await pool.request(server, scope, send)
    except AuthRequired:
        await authorize(context, server)
        return await pool.request(server, scope, send)
    except ConnectionError as error:
        raise ToolError(str(error), code="mcp_disconnected") from None


class MCPTool(Tool):
    def __init__(self, server: MCPServer, meta: Any, name: str) -> None:
        hints = server_hints(meta)
        annotations: dict[str, Any] = {"open_world": True}
        if server.trust_hints and hints.get("read_only"):
            annotations["read_only"] = True
        if server.trust_hints and hints.get("destructive"):
            annotations["destructive"] = True

        description = meta.description or strings.TOOL_DEFAULT_DESCRIPTION.format(name=meta.name)
        if server.description:
            description = f"[{server.name}：{server.description}] {description}"

        super().__init__(
            None,
            name=name,
            description=description,
            input_schema=getattr(meta, "input_schema", None)
            or getattr(meta, "inputSchema", None)
            or {"type": "object"},
            timeout=server.tool_timeout,
            annotations=annotations,
        )
        self.server = server
        self.hints = hints
        self.remote_name = meta.name

    async def run(self, context: Context, args: dict[str, Any]) -> ToolResult:
        response = await call_server(context, self.server, lambda client: client.call_tool(self.remote_name, args))
        return to_tool_result(response, self.server.name)


class ConnectTool(Tool):
    def __init__(self, server: MCPServer) -> None:
        super().__init__(
            None,
            name=f"connect_{server.name}"[:64],
            description=strings.AUTHORIZE_DESCRIPTION.format(server=server.name),
            input_schema={"type": "object", "properties": {}},
            annotations={"interactive": True},
        )
        self.server = server

    async def run(self, context: Context, args: dict[str, Any]) -> str:
        if not await context.service(MCPService).pool.authorized(self.server):
            await authorize(context, self.server)
        return strings.AUTHORIZED.format(server=self.server.name)


class ListResourcesTool(Tool):
    def __init__(self, server: MCPServer) -> None:
        super().__init__(
            None,
            name=f"mcp__{server.name}__list_resources"[:64],
            description=strings.LIST_RESOURCES_DESCRIPTION.format(server=server.name),
            input_schema={"type": "object", "properties": {}},
            timeout=server.tool_timeout,
            parallel=True,
            annotations={"read_only": True, "open_world": True},
        )
        self.server = server

    async def run(self, context: Context, args: dict[str, Any]) -> ToolResult:
        resources = await call_server(
            context, self.server, lambda client: list_all_pages(client.list_resources, "resources")
        )
        items = [
            {"uri": str(resource.uri), "name": resource.name, "description": resource.description}
            for resource in resources
        ]
        lines = [
            f"- {item['uri']} {item['name']}" + (f"：{item['description']}" if item["description"] else "")
            for item in items
        ]
        text = wrap_external(self.server.name, "\n".join(lines)) if lines else strings.NO_RESOURCES
        return ToolResult(text=text, data=items)


class ReadResourceTool(Tool):
    def __init__(self, server: MCPServer) -> None:
        super().__init__(
            None,
            name=f"mcp__{server.name}__read_resource"[:64],
            description=strings.READ_RESOURCE_DESCRIPTION.format(server=server.name),
            input_schema={
                "type": "object",
                "properties": {"uri": {"type": "string", "description": strings.RESOURCE_URI}},
                "required": ["uri"],
            },
            timeout=server.tool_timeout,
            parallel=True,
            annotations={"read_only": True, "open_world": True},
        )
        self.server = server

    async def run(self, context: Context, args: dict[str, Any]) -> ToolResult:
        response = await call_server(context, self.server, lambda client: client.read_resource(args["uri"]))
        parts: list[Any] = []
        for content in response.contents:
            if getattr(content, "text", None) is not None:
                parts.append(TextPart(text=wrap_external(self.server.name, content.text)))
            elif getattr(content, "blob", None):
                mime = content.mime_type or "application/octet-stream"
                if mime.startswith("image/"):
                    parts.append(MediaPart(kind="image", mime=mime, data=content.blob))
                else:
                    parts.append(TextPart(text=strings.BINARY_RESOURCE.format(uri=content.uri, mime=mime)))

        if not parts:
            raise ToolError(f"资源 {args['uri']} 无内容", code="not_found")
        return ToolResult(content=parts)
