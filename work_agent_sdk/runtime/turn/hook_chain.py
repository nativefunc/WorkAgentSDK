from __future__ import annotations

import logging
import traceback
from typing import TYPE_CHECKING, Any

from work_agent_sdk.core.errors import HookFailed
from work_agent_sdk.core.events import HookApplied
from work_agent_sdk.core.hooks import Deny, Hooks, Reply
from work_agent_sdk.runtime.context import Suspended

if TYPE_CHECKING:
    from work_agent_sdk.runtime.context import RunContext
    from work_agent_sdk.runtime.worker.worker import SessionWorker

logger = logging.getLogger("work_agent_sdk")


class HookChain:
    def __init__(self, worker: SessionWorker) -> None:
        self.worker = worker
        self.hooks = worker.hooks

    def _hooks_for(self, point: str, tool_name: str | None) -> list[Hooks]:
        return [hook for hook in self.hooks if hook.implements(point) and hook.applies_to(point, tool_name)]

    async def _record_applied(self, ctx: RunContext, hook: Hooks, point: str, action: str, detail: str = "") -> None:
        await self.worker.append(
            HookApplied(
                hook=repr(hook),
                point=point,
                action=action,
                detail=detail[:2000],
                call_id=ctx.call.id if ctx.call else None,
                turn_id=ctx.turn_id,
            )
        )

    async def _run_hook(self, hook: Hooks, point: str, ctx: RunContext, *arguments: Any) -> Any:
        try:
            return await getattr(hook, point)(ctx, *arguments)
        except Suspended:
            raise
        except Exception as error:
            logger.debug("钩子执行出错\n%s", traceback.format_exc())
            await self._record_applied(ctx, hook, point, "error", f"{type(error).__name__}: {error}")
            raise HookFailed(repr(hook), point, error) from error

    async def before(self, point: str, ctx: RunContext, value: Any, *, tool_name: str | None = None) -> Any:
        for hook in self._hooks_for(point, tool_name):
            result = await self._run_hook(hook, point, ctx, value)
            if result is None:
                continue
            if isinstance(result, Deny):
                await self._record_applied(ctx, hook, point, "deny", result.message)
                return result
            if isinstance(result, Reply):
                await self._record_applied(ctx, hook, point, "reply")
                return result

            value = result
            await self._record_applied(ctx, hook, point, "rewrite")

        return value

    async def after(self, point: str, ctx: RunContext, *arguments: Any, tool_name: str | None = None) -> Any:
        value = arguments[-1]
        for hook in self._hooks_for(point, tool_name):
            result = await self._run_hook(hook, point, ctx, *arguments[:-1], value)
            if result is not None:
                value = result
                await self._record_applied(ctx, hook, point, "rewrite")

        return value

    async def first_result(self, point: str, ctx: RunContext, *arguments: Any) -> Any:
        for hook in self._hooks_for(point, None):
            result = await self._run_hook(hook, point, ctx, *arguments)
            if result is not None:
                action = "continue" if point == "before_turn_end" else "recover"
                await self._record_applied(ctx, hook, point, action)
                return result
        return None
