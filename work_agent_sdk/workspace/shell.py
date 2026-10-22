from __future__ import annotations

import asyncio
from typing import Annotated

from pydantic import Field

import work_agent_sdk.strings.workspace as strings
from work_agent_sdk.core.errors import ToolError
from work_agent_sdk.core.messages import ToolResult
from work_agent_sdk.core.tool import Context, Tool, Toolset
from work_agent_sdk.core.utils import head_and_tail
from work_agent_sdk.workspace.service import WorkspaceService

ENDED = ("exited", "killed")

RISK = {"destructive": True, "open_world": True}


class Shell(Toolset):
    """
    在会话的工作区中执行命令，命令都经过沙箱。allow_unsandboxed=True 时模型可申请在沙箱外执行，框架不做审批，
    需自行添加审批钩子。
    """

    name = "shell"
    description = "在工作区中执行命令"
    needs = (WorkspaceService,)
    requires = frozenset({"workspace"})

    def __init__(
        self,
        *,
        timeout: float = 30,
        max_timeout: float = 600,
        max_output: int = 30_000,
        max_output_mb: float = 10,
        max_processes: int = 50,
        allow_unsandboxed: bool = False,
    ) -> None:
        self.timeout = timeout
        self.max_timeout = max_timeout
        self.max_output = max_output
        self.max_output_mb = max_output_mb
        self.max_processes = max_processes
        self.allow_unsandboxed = allow_unsandboxed
        super().__init__()
        self._shell = self._build_shell_tool()
        self._input = Tool(
            self._shell_input,
            name="shell_input",
            description=strings.SHELL_INPUT_DESCRIPTION,
            annotations=RISK,
        )

    def __repr__(self) -> str:
        return "Shell()"

    async def tools(self, context: Context) -> list[Tool]:
        # 创建会话时已按 requires 检查工作区；节点暂时离线时仍提供工具，执行时再连接
        return [self._shell, self._input]

    def _build_shell_tool(self) -> Tool:
        function = self._shell_command_with_escape if self.allow_unsandboxed else self._shell_command
        return Tool(function, name="shell", description=self._describe, annotations=RISK)

    async def _shell_command(
        self,
        ctx: Context,
        command: Annotated[str, Field(description=strings.SHELL_COMMAND)],
        timeout: Annotated[float | None, Field(description=strings.SHELL_TIMEOUT_ARG)] = None,
        background: Annotated[bool, Field(description=strings.SHELL_BACKGROUND_ARG)] = False,
    ) -> ToolResult:
        return await self._run(ctx, command, timeout, background, False)

    async def _shell_command_with_escape(
        self,
        ctx: Context,
        command: Annotated[str, Field(description=strings.SHELL_COMMAND)],
        timeout: Annotated[float | None, Field(description=strings.SHELL_TIMEOUT_ARG)] = None,
        background: Annotated[bool, Field(description=strings.SHELL_BACKGROUND_ARG)] = False,
        unsandboxed: Annotated[bool, Field(description=strings.SHELL_UNSANDBOXED_ARG)] = False,
        unsandboxed_reason: Annotated[str | None, Field(description=strings.SHELL_UNSANDBOXED_REASON_ARG)] = None,
    ) -> ToolResult:
        if unsandboxed and not (unsandboxed_reason or "").strip():
            raise ToolError("unsandboxed=true 时必须提供 unsandboxed_reason", code="invalid_arguments")
        return await self._run(ctx, command, timeout, background, unsandboxed)

    async def _describe(self, context: Context) -> str:
        # 工作区路径、系统和沙箱限制会变化，放在对话的运行环境说明中，不写入工具说明
        lines = [strings.SHELL_DESCRIPTION]
        if self.allow_unsandboxed:
            lines.append(strings.SHELL_UNSANDBOXED)

        lines.append(strings.SHELL_TIMEOUT.format(timeout=self.timeout, max_timeout=self.max_timeout))
        lines.append(strings.SHELL_BACKGROUND)
        return "\n".join(lines)

    async def _run(
        self, context: Context, command: str, timeout: float | None, background: bool, unsandboxed: bool
    ) -> ToolResult:
        workspace = context.workspace
        if workspace is None:
            raise ToolError("当前会话未配置工作区", code="no_workspace")

        key = context.step_key("process")
        running = [
            process for process in await workspace.processes() if process.status == "running" and process.key != key
        ]
        if len(running) >= self.max_processes:
            raise ToolError(
                f"当前会话已有 {len(running)} 个进程在运行，达到上限 {self.max_processes}；"
                "请先用 shell_input（kill=true）终止不需要的进程，再启动新进程",
                code="too_many_processes",
            )

        try:
            process = await workspace.start_process(
                command,
                background=background,
                key=key,
                call_id=context.call.id if context.call is not None else None,
                unsandboxed=unsandboxed,
                max_output_mb=self.max_output_mb,
            )
        except PermissionError as error:
            # 设备策略不允许：仅开放文件读写，或不允许沙箱外执行
            raise ToolError(str(error), code="not_allowed") from None

        if background:
            return ToolResult(
                text=strings.SHELL_STARTED_IN_BACKGROUND.format(process_id=process.id),
                data={"process_id": process.id, "running": True},
            )

        wait = min(timeout or self.timeout, self.max_timeout)

        async def follow() -> None:
            # 前台命令的输出实时推送到本次调用（仅推送，不持久化）
            async for piece in process.output(0, follow=True):
                await context.stream({"process_id": process.id, "offset": piece.offset, "text": piece.text})

        streaming = asyncio.ensure_future(follow())
        try:
            _, finished = await process.wait_output(wait)
        finally:
            streaming.cancel()
            # 只收回推送任务自身的取消或错误；本次调用被取消时，取消照常向上传递
            await asyncio.gather(streaming, return_exceptions=True)

        if not finished:
            finished = not await process.move_to_background()

        await process.refresh()
        output = await process.text()
        if not finished:
            await process.mark_seen(seen_offset=len(output.encode()))
            shown = head_and_tail(output, self.max_output)
            return ToolResult(
                text=shown.rstrip() + "\n" + strings.SHELL_MOVED_TO_BACKGROUND.format(wait=wait, process_id=process.id),
                data={"process_id": process.id, "running": True},
            )

        await process.mark_seen(seen_offset=len(output.encode()))
        return self._exit_result(process.id, process.exit_code, output)

    def _exit_result(self, process_id: str, exit_code: int | None, output: str) -> ToolResult:
        shown = head_and_tail(output, self.max_output)
        lines = [shown.rstrip() or strings.SHELL_NO_OUTPUT]
        if len(output) > self.max_output:
            lines.append(strings.SHELL_OUTPUT_TRUNCATED)

        lines.append(strings.SHELL_EXIT_CODE.format(exit_code=exit_code))
        return ToolResult(
            text="\n".join(lines),
            data={
                "process_id": process_id,
                "exit_code": exit_code,
                "running": False,
            },
        )

    async def _shell_input(
        self,
        ctx: Context,
        process_id: Annotated[str, Field(description=strings.SHELL_INPUT_PROCESS_ID)],
        text: Annotated[str | None, Field(description=strings.SHELL_INPUT_TEXT)] = None,
        wait: Annotated[float, Field(description=strings.SHELL_INPUT_WAIT)] = 3,
        kill: Annotated[bool, Field(description=strings.SHELL_INPUT_KILL)] = False,
    ) -> ToolResult:
        try:
            if ctx.workspace is None:
                raise LookupError(process_id)
            process = await ctx.workspace.process(process_id)
        except LookupError:
            raise ToolError(f"当前会话中不存在进程 {process_id}", code="not_found") from None

        if process.session_id != ctx.session_id:
            raise ToolError(f"进程 {process_id} 属于子智能体，不属于当前会话", code="not_found")

        if kill:
            await process.kill()
            await process.wait()
        elif text is not None:
            await process.write(text + "\n")

        if process.status not in ENDED and not kill:
            await process.wait_output(min(wait, self.max_timeout))

        await process.refresh()
        start = process.seen_offset
        output = await process.text(start)
        finished = process.status in ENDED
        await process.mark_seen(seen_offset=start + len(output.encode()))
        lines = [head_and_tail(output, self.max_output).rstrip() or strings.SHELL_INPUT_NO_OUTPUT]
        if finished:
            lines.append(strings.SHELL_INPUT_ENDED.format(exit_code=process.exit_code))
        else:
            lines.append(strings.SHELL_INPUT_RUNNING.format(process_id=process_id))

        return ToolResult(
            text="\n".join(lines),
            data={"process_id": process_id, "running": not finished, "exit_code": process.exit_code},
        )
