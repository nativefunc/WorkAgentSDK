from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import work_agent_sdk.strings.runtime as strings
from work_agent_sdk.core.errors import ErrorInfo, TurnFailed, TurnRejected
from work_agent_sdk.core.events import (
    MessageCompleted,
    MessageStarted,
    MessageUpdated,
    ModelCalled,
    ModelRetried,
)
from work_agent_sdk.core.hooks import Deny, Reply
from work_agent_sdk.core.messages import (
    AssistantMessage,
    CustomMessage,
    ToolResultMessage,
    Usage,
)
from work_agent_sdk.core.utils import maybe_await, new_id
from work_agent_sdk.models.base import ModelRequest, ModelSettings
from work_agent_sdk.models.call import ModelCall
from work_agent_sdk.models.errors import ModelError
from work_agent_sdk.runtime.turn.catalog import SUBMIT_TOOL, collect, schema_of
from work_agent_sdk.runtime.turn.view import model_view, normalize

if TYPE_CHECKING:
    from work_agent_sdk.runtime.context import RunContext
    from work_agent_sdk.runtime.turn.segment import Segment


class ModelStep:
    def __init__(self, segment: Segment) -> None:
        self.segment = segment
        self.worker = segment.worker

    async def build_request(self, ctx: RunContext) -> ModelRequest:
        worker = self.worker
        agent = worker.agent
        model = worker.model
        system = str(await maybe_await(agent.instructions(ctx)) if callable(agent.instructions) else agent.instructions)
        state = await worker.state()
        if any(isinstance(message, CustomMessage) and message.for_model for message in state.messages):
            system = f"{system}\n\n{strings.CONTEXT_NOTE}".strip()
        if any(isinstance(message, ToolResultMessage) and message.open_world for message in state.messages):
            system = f"{system}\n\n{strings.UNTRUSTED_NOTE}".strip()

        catalog = await collect(worker, ctx)
        output_schema = catalog.output_schema
        if agent.output is not None:
            extra = strings.OUTPUT_JSON if output_schema is not None else strings.OUTPUT_SUBMIT.format(tool=SUBMIT_TOOL)
            system = f"{system}\n\n{extra}".strip()

        self.segment.native_output = output_schema is not None
        tools = [await schema_of(entry.tool, ctx) for entry in catalog.direct()]
        deferred = sorted(
            [await schema_of(entry.tool, ctx) for entry in catalog.deferred()], key=lambda item: item["name"]
        )
        config = worker.record.config
        thinking = config.thinking or agent.thinking
        return ModelRequest(
            model=model,
            system=system.strip(),
            messages=model_view(state),
            tools=tools,
            deferred_tools=deferred,
            thinking=thinking,
            settings=agent.model_settings or ModelSettings(),
            output_schema=output_schema,
            ctx=ctx,
        )

    async def call(self) -> AssistantMessage:
        ctx = self.segment.new_context()
        request = await self.build_request(ctx)
        original = request.messages
        decision = await self.segment.hooks.before("before_model", ctx, request)
        if isinstance(decision, Deny):
            raise TurnRejected(decision.error_info())

        if isinstance(decision, Reply):
            reply = decision.content
            message = (
                reply if isinstance(reply, AssistantMessage) else AssistantMessage(text=str(reply), stop_reason="stop")
            )
            message = message.model_copy(
                update={"id": new_id("msg_"), "status": "completed", "turn_id": self.segment.turn_id}
            )
        else:
            if decision.messages is not original:
                decision.messages = normalize(decision.messages)
            message = await self._stream(decision, ctx)

        message = await self.segment.hooks.after("after_model", ctx, message)
        message = message.model_copy(
            update={"status": "completed", "turn_id": self.segment.turn_id, "completed_at": time.time()}
        )
        await self.worker.append(MessageCompleted(message=message, turn_id=self.segment.turn_id))
        return message

    async def _stream(self, request: ModelRequest, ctx: RunContext, retried: bool = False) -> AssistantMessage:
        worker = self.worker
        turn_id = self.segment.turn_id
        message_id = new_id("msg_")
        started_message = AssistantMessage(id=message_id, status="in_progress", turn_id=turn_id, model=request.model.id)
        await worker.append(MessageStarted(message=started_message, turn_id=turn_id))

        async def on_delta(delta: dict[str, Any]) -> None:
            await worker.append(MessageUpdated(message_id=message_id, delta=delta, ephemeral=True, turn_id=turn_id))

        async def on_retry(model: Any, attempt: int, delay: float, error: ModelError) -> None:
            await worker.append(
                ModelRetried(
                    attempt=attempt,
                    delay=round(delay, 2),
                    error=error.message[:500],
                    error_code=error.code,
                    turn_id=turn_id,
                )
            )

        call = ModelCall(request, on_delta=on_delta, on_retry=on_retry)
        worker.live[message_id] = call
        started = time.time()
        try:
            message = await call.run()
        except asyncio.CancelledError:
            if not self.segment.shutdown:
                await self._save_partial(call, message_id, "cancelled", "stopped")
            raise
        except ModelError as error:
            await self._record_model_call(call, started, error)
            recovery = None if retried else await self.segment.hooks.first_result("on_model_error", ctx, request, error)
            if isinstance(recovery, ModelRequest):
                await self._save_partial(call, message_id, "failed", "error", error)
                return await self._stream(recovery, ctx, retried=True)
            if recovery is not None:
                await self._save_partial(call, message_id, "failed", "error", error)
                return (
                    recovery
                    if isinstance(recovery, AssistantMessage)
                    else AssistantMessage(text=str(recovery), stop_reason="stop")
                )

            await self._save_partial(call, message_id, "failed", "error", error)
            raise TurnFailed(
                ErrorInfo(code=error.code, message=error.message, source="model", retryable=error.retryable)
            ) from error
        except Exception:
            # 不是模型接口的错误（如写存储失败）：结束进行中的回答，本轮以 internal 错误结束
            await self._save_partial(call, message_id, "failed", "error")
            raise
        finally:
            worker.live.pop(message_id, None)

        await self._record_model_call(call, started, None)
        return message.model_copy(update={"id": message_id})

    async def _save_partial(
        self,
        call: ModelCall,
        message_id: str,
        status: str,
        stop_reason: str,
        error: ModelError | None = None,
    ) -> None:
        partial = call.builder.message()
        partial = partial.model_copy(
            update={
                "id": message_id,
                "status": status,
                "tool_calls": [],
                "stop_reason": stop_reason,
                "error": error.message if error else None,
                "error_code": error.code if error else None,
                "turn_id": self.segment.turn_id,
                "model": call.model.id,
                "completed_at": time.time(),
            }
        )
        await self.worker.append(MessageCompleted(message=partial, turn_id=self.segment.turn_id))

    async def _record_model_call(self, call: ModelCall, started: float, error: ModelError | None) -> None:
        builder = call.builder
        if builder.usage is not None:
            self.segment.usage = self.segment.usage + builder.usage

        await self.worker.append(
            ModelCalled(
                model=call.model.id,
                duration=round(time.time() - started, 3),
                first_token=round(builder.first_token_at - started, 3) if builder.first_token_at else None,
                usage=builder.usage or Usage(),
                retries=max(0, call.attempts - 1),
                error=error.message[:500] if error else None,
                error_code=error.code if error else None,
                turn_id=self.segment.turn_id,
            )
        )
