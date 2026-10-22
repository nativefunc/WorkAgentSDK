from __future__ import annotations

import asyncio
import json
import traceback
from typing import TYPE_CHECKING, Any

import jsonschema
from pydantic import ValidationError

import work_agent_sdk.strings.runtime as strings
from work_agent_sdk.core.errors import HookFailed, NodeOffline, ToolError
from work_agent_sdk.core.events import MessageStarted, MessageUpdated
from work_agent_sdk.core.hooks import Deny, Reply
from work_agent_sdk.core.messages import (
    MediaPart,
    TextPart,
    ToolCall,
    ToolResult,
    ToolResultMessage,
)
from work_agent_sdk.core.tool import to_result
from work_agent_sdk.runtime.context import CallScope, RunContext, Suspended
from work_agent_sdk.runtime.turn.catalog import Catalog, Entry, collect

if TYPE_CHECKING:
    from work_agent_sdk.runtime.turn.segment import Segment
    from work_agent_sdk.runtime.worker.state import CallState


def validation_text(error: Exception) -> str:
    if isinstance(error, ValidationError):
        problems = []
        for item in error.errors()[:10]:
            location = ".".join(str(step) for step in item.get("loc", ())) or "参数"
            problems.append(f"{location}：{item.get('msg')}")
        return strings.INVALID_ARGUMENTS.format(problems="；".join(problems))
    if isinstance(error, jsonschema.ValidationError):
        location = ".".join(str(step) for step in error.absolute_path) or "参数"
        return strings.INVALID_ARGUMENTS.format(problems=f"{location}：{error.message}")
    return strings.INVALID_ARGUMENTS.format(problems=str(error))


class ToolStep:
    def __init__(self, segment: Segment) -> None:
        self.segment = segment
        self.worker = segment.worker

    async def run(self, calls: list[CallState]) -> str:
        catalog = await collect(self.worker, self.segment.new_context())
        groups: list[list[CallState]] = []
        for call in calls:
            if groups and _is_parallel(catalog, call) and _is_parallel(catalog, groups[-1][-1]):
                groups[-1].append(call)
            else:
                groups.append([call])

        for group in groups:
            state = await self.worker.state()
            runnable = [
                call
                for call in group
                if not state.call_finished(call) and (not state.call_started(call) or state.resumable(call))
            ]
            blocked = any(
                state.call_waiting(call) and not state.resumable(call) for call in group if call not in runnable
            )
            outcomes = await asyncio.gather(*(self.execute(call, catalog) for call in runnable)) if runnable else []
            if blocked or "waiting" in outcomes:
                return "waiting"
            if "end" in outcomes:
                # 本轮结束：后续分组的调用不再执行，模型视图中显示为“该调用未执行”
                return "end"

        return "done"

    async def execute(self, call_state: CallState, catalog: Catalog) -> str:
        worker = self.worker
        state = await worker.state()
        call = ToolCall(id=call_state.id, name=call_state.name, args=call_state.args)
        entry = catalog.get(call.name)
        if entry is not None and entry.deferred and call.name not in self.segment.loaded_tools(state):
            entry = None  # 尚未通过 tool_search 加载

        tool = entry.tool if entry else None
        result_message = state.result_of(call_state)
        if result_message is None:
            result_message = ToolResultMessage(
                tool_call_id=call.id,
                tool_name=call.name,
                status="in_progress",
                open_world=bool(tool and tool.open_world),
                turn_id=self.segment.turn_id,
            )
            await worker.append(MessageStarted(message=result_message, turn_id=self.segment.turn_id))
        else:
            await worker.append(
                MessageUpdated(
                    message_id=result_message.id, changes={"status": "in_progress"}, turn_id=self.segment.turn_id
                )
            )

        state = await worker.state()
        call_state = state.calls[call.id]
        scope = CallScope(call_state, result_message.id)
        ctx = self.segment.new_context(
            tool=tool, call=call, scope=scope, declared=entry.requires if entry else frozenset()
        )
        self.segment.running_calls[call.id] = result_message.id
        try:
            return await self._run_with_hooks(ctx, scope, call, entry)
        finally:
            self.segment.running_calls.pop(call.id, None)

    async def _run_with_hooks(self, ctx: RunContext, scope: CallScope, call: ToolCall, entry: Entry | None) -> str:
        hooks = self.segment.hooks
        message_id = scope.result_message_id

        if entry is None:
            await self._complete_result(
                ctx,
                call,
                None,
                message_id,
                ToolResult(error=strings.UNKNOWN_TOOL.format(name=call.name), error_code="unknown_tool"),
            )
            return "done"

        tool = entry.tool
        try:
            tool.validate_args(call.args)
        except (ValidationError, jsonschema.ValidationError) as error:
            await self._complete_result(
                ctx, call, tool, message_id, ToolResult(error=validation_text(error), error_code="invalid_arguments")
            )
            return "done"

        end_turn = tool.end_turn
        try:
            decision = await hooks.before("before_tool", ctx, call, tool_name=call.name)
            if isinstance(decision, Deny):
                result = ToolResult(error=decision.message, error_code=decision.code or "denied", data=decision.data)
            elif isinstance(decision, Reply):
                result = to_result(decision.content)
            elif decision.name != call.name:
                result = ToolResult(error=strings.HOOK_RENAMED, error_code="hook_error")
            else:
                ctx.call = decision
                await self.worker.resources.bind_all(entry.requires)
                result = await self._invoke(ctx, tool, decision)
        except Suspended:
            await self._mark_waiting(ctx, message_id)
            return "waiting"
        except HookFailed as failure:
            result = ToolResult(error=strings.HOOK_ERROR.format(error=failure.error), error_code="hook_error")
        except ToolError as error:
            result = ToolResult(error=error.message, error_code=error.code or "tool_error", data=error.data)
            end_turn = end_turn or error.end_turn
            if error.code == "timeout":
                await self._notify_cancelled(call)
        except NodeOffline as error:
            result = ToolResult(error=str(error), error_code="node_offline")
        except (ValidationError, jsonschema.ValidationError) as error:
            result = ToolResult(error=validation_text(error), error_code="invalid_arguments")
        except asyncio.CancelledError:
            await self._complete_cancelled(ctx, call, message_id)
            raise
        except Exception as error:
            result = ToolResult(
                error=strings.TOOL_FAILED.format(error=f"{type(error).__name__}: {error}"),
                error_code="tool_error",
                data={"trace": traceback.format_exc(limit=20)},
            )

        try:
            result = await hooks.after("after_tool", ctx, ctx.call or call, result, tool_name=call.name)
        except Suspended:
            await self._mark_waiting(ctx, message_id)
            return "waiting"
        except HookFailed as failure:
            result = ToolResult(error=strings.HOOK_RESULT_ERROR.format(error=failure.error), error_code="hook_error")
        except asyncio.CancelledError:
            await self._complete_cancelled(ctx, call, message_id)
            raise

        await self._complete_result(ctx, call, tool, message_id, to_result(result))
        return "end" if end_turn or scope.end_turn else "done"

    async def _invoke(self, ctx: RunContext, tool: Any, call: ToolCall) -> ToolResult:
        task = asyncio.ensure_future(tool.invoke(ctx, call.args))
        try:
            return await task
        except asyncio.CancelledError:
            task.cancel()
            # 等待工具完成收尾（例如记录刚启动的进程），再通知终止该调用的前台命令
            await asyncio.wait([task], timeout=10)
            raise

    async def _mark_waiting(self, ctx: RunContext, message_id: str) -> None:
        await self.worker.append(
            MessageUpdated(message_id=message_id, changes={"status": "waiting"}, turn_id=self.segment.turn_id)
        )

    async def _notify_cancelled(self, call: ToolCall) -> None:
        await self.worker.lifecycle.notify("call_cancelled", await self.worker.session_ref(), call.id)

    async def _complete_cancelled(self, ctx: RunContext, call: ToolCall, message_id: str) -> None:
        # 后端关闭时不写入任何内容，重启后恢复
        if self.segment.shutdown:
            return

        text = strings.NOT_COMPLETED.format(reason=strings.REASON_STOPPED)
        await self.worker.complete_tool_result(
            message_id, status="cancelled", content=[TextPart(text=text)], error=text, error_code="cancelled"
        )
        await self._notify_cancelled(call)

    async def _complete_result(
        self, ctx: RunContext, call: ToolCall, tool: Any, message_id: str, result: ToolResult
    ) -> None:
        limit = self.worker.model.max_image_bytes
        content: list[Any] = []
        for part in result.content:
            if isinstance(part, MediaPart) and part.kind == "image" and limit and len(part.data) > limit:
                content.append(
                    TextPart(text=strings.IMAGE_TOO_LARGE.format(size=len(part.data) / 1e6, limit=limit / 1e6))
                )
            else:
                content.append(part)

        if not content and result.error is None and result.data is not None:
            content = [TextPart(text=json.dumps(result.data, ensure_ascii=False, default=str))]

        await self.worker.complete_tool_result(
            message_id,
            status="failed" if result.error else "completed",
            content=content,
            data=result.data,
            error=result.error,
            error_code=result.error_code,
            loaded_tools=[] if result.error else list(result.loaded_tools),
        )


def _is_parallel(catalog: Catalog, call: CallState) -> bool:
    entry = catalog.get(call.name)
    return entry is not None and entry.tool.parallel
