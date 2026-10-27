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
    Run commands in the session's workspace; all commands go through the sandbox. With allow_unsandboxed=True the model may request to run outside the sandbox.
    The SDK doesn't approve such requests; add an approval hook.
    """

    name = "shell"
    description = "Run commands in the workspace"
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
        # The workspace was checked against requires when the session was created; while the node is temporarily offline the tools are still offered and it connects when running
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
            raise ToolError("unsandboxed_reason is required when unsandboxed=true", code="invalid_arguments")
        return await self._run(ctx, command, timeout, background, unsandboxed)

    async def _describe(self, context: Context) -> str:
        # The workspace path, OS and sandbox limits can change, so they go in the conversation's environment description rather than the tool description
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
            raise ToolError("No workspace is configured for this session", code="no_workspace")

        key = context.step_key("process")
        running = [
            process for process in await workspace.processes() if process.status == "running" and process.key != key
        ]
        if len(running) >= self.max_processes:
            raise ToolError(
                f"The current session already has {len(running)} processes running, reaching the limit of {self.max_processes}; "
                "terminate processes you don't need with shell_input (kill=true) before starting new ones",
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
            # Not allowed by the device policy: only file read/write is exposed, or running outside the sandbox isn't allowed
            raise ToolError(str(error), code="not_allowed") from None

        if background:
            return ToolResult(
                text=strings.SHELL_STARTED_IN_BACKGROUND.format(process_id=process.id),
                data={"process_id": process.id, "running": True},
            )

        wait = min(timeout or self.timeout, self.max_timeout)

        async def follow() -> None:
            # Foreground command output is pushed live to the current call (pushed only, not persisted)
            async for piece in process.output(0, follow=True):
                await context.stream({"process_id": process.id, "offset": piece.offset, "text": piece.text})

        streaming = asyncio.ensure_future(follow())
        try:
            _, finished = await process.wait_output(wait)
        finally:
            streaming.cancel()
            # Only absorb cancellation or errors from the push task itself; if this call is cancelled, the cancellation propagates as usual
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
            raise ToolError(f"Process {process_id} doesn't exist in the current session", code="not_found") from None

        if process.session_id != ctx.session_id:
            raise ToolError(f"Process {process_id} belongs to a subagent, not the current session", code="not_found")

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
