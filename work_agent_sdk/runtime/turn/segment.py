from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter, ValidationError

import work_agent_sdk.strings.runtime as strings
from work_agent_sdk.core.errors import (
    ConfigError,
    ErrorInfo,
    HookFailed,
    TurnFailed,
    TurnRejected,
)
from work_agent_sdk.core.events import MessageCompleted, TurnEnded, TurnStarted
from work_agent_sdk.core.hooks import MAX_CONTINUES, Continue, Deny, Reply
from work_agent_sdk.core.messages import (
    AssistantMessage,
    CustomMessage,
    Message,
    TextPart,
    ToolResultMessage,
    Usage,
)
from work_agent_sdk.core.results import TurnResult
from work_agent_sdk.runtime.context import RunContext, TurnInfo, jsonable
from work_agent_sdk.runtime.turn.catalog import SUBMIT_TOOL
from work_agent_sdk.runtime.turn.facts import changed_facts
from work_agent_sdk.runtime.turn.hook_chain import HookChain
from work_agent_sdk.runtime.turn.model_step import ModelStep
from work_agent_sdk.runtime.turn.tool_step import ToolStep, validation_text
from work_agent_sdk.runtime.worker.state import CONTINUE_KIND, OUTPUT_PROBLEM_KIND

if TYPE_CHECKING:
    from work_agent_sdk.runtime.worker.worker import SessionWorker
    from work_agent_sdk.store import QueueItem

logger = logging.getLogger("work_agent_sdk")
MAX_OUTPUT_RETRIES = 3


class Segment:
    def __init__(self, worker: SessionWorker, turn_id: str, phase: str, items: list[QueueItem] | None = None) -> None:
        self.worker = worker
        self.turn_id = turn_id
        self.phase = phase
        self.items = list(items or [])
        self.info = TurnInfo(id=turn_id, phase=phase)
        self.hooks = HookChain(worker)
        self.shutdown = False
        self.usage = Usage()
        self.running_calls: dict[str, str] = {}
        self.native_data: Any = None
        self.has_native_data = False

        # Whether the latest model request used native structured output (set by ModelStep according to the tool catalog's decision)
        self.native_output = False

    def new_context(self, **fields: Any) -> RunContext:
        return RunContext(self.worker, turn=self.info, **fields)

    def loaded_tools(self, state: Any) -> set[str]:
        names: set[str] = set()
        for message_id in state.completion_order:
            if message_id in state.hidden:
                continue
            message = state.by_id[message_id]
            if isinstance(message, ToolResultMessage) and message.status == "completed":
                names.update(message.loaded_tools)
        return names

    async def run(self) -> TurnResult:
        worker = self.worker
        state = await worker.state()
        if self.phase == "new":
            first = self.items[0] if self.items else None
            metadata: dict[str, Any] = {}
            for item in self.items:
                metadata.update(item.metadata)

            source = first.source if first else "user"
        else:
            turn = state.turns.get(self.turn_id)
            source = turn.source if turn else "user"
            metadata = dict(turn.metadata) if turn else {}

        self.info.source = source
        self.info.metadata = metadata
        await worker.append(
            TurnStarted(
                phase=self.phase,
                source=source,
                metadata=metadata,
                turn_id=self.turn_id,
            )
        )
        await worker.lifecycle.notify("turn_started", await worker.session_ref(), self.turn_id, self.phase)
        status = "completed"
        error: ErrorInfo | None = None
        try:
            await self._interrupt_stale()
            replied = False
            if self.phase == "recover":
                await self._recover()
            elif self.phase == "new":
                replied = await self._intake()

            if not replied:
                await self._add_changed_facts()
                status = await self._loop()
        except asyncio.CancelledError:
            if self.shutdown:
                raise

            current = asyncio.current_task()
            if current is not None:
                current.uncancel()

            status = "stopped"
        except TurnRejected as rejection:
            status, error = "rejected", rejection.info
        except TurnFailed as failure:
            status, error = "error", failure.info
        except HookFailed as failure:
            status, error = "error", ErrorInfo(code="hook_error", message=str(failure), source="hook")
        except ConfigError as problem:
            status, error = "error", ErrorInfo(code="config_error", message=str(problem))
        except Exception as unexpected:
            logger.exception("Error running a turn of session %s", worker.session_id)
            status = "error"
            error = ErrorInfo(code="internal", message=f"{type(unexpected).__name__}: {unexpected}")

        return await self._finish(status, error)

    async def _finish(self, status: str, error: ErrorInfo | None) -> TurnResult:
        worker = self.worker
        if status != "waiting":
            # The turn already has a final result: also clean up whatever it's still waiting on (cleanup on stop happens here too)
            await worker.end_waits(self.turn_id, "unanswered" if status == "cancelled" else "cancelled")

        result = await self.build_result(status, error)
        await worker.append(TurnEnded(result=result, turn_id=self.turn_id))
        await worker.lifecycle.notify("turn_ended", await worker.session_ref(), result)
        return result

    async def build_result(self, status: str, error: ErrorInfo | None) -> TurnResult:
        worker = self.worker
        state = await worker.state()
        text = ""
        data: Any = None
        for message_id in reversed(state.completion_order):
            message = state.by_id[message_id]
            if message.turn_id != self.turn_id:
                continue
            if not text and isinstance(message, AssistantMessage) and message.status == "completed" and message.text:
                text = message.text
            if (
                data is None
                and isinstance(message, ToolResultMessage)
                and message.tool_name == SUBMIT_TOOL
                and message.status == "completed"
            ):
                data = message.data

        if data is None and self.has_native_data:
            data = self.native_data

        pending = await worker.pending(children=True) if status == "waiting" else []
        return TurnResult(
            turn_id=self.turn_id, status=status, text=text, data=data, pending=pending, error=error, usage=self.usage
        )

    async def _interrupt_stale(self) -> None:
        state = await self.worker.state()
        started_at = self.worker.core.started_at
        for message in state.unfinished_messages():
            if isinstance(message, CustomMessage) and message.created_at < started_at:
                await self.worker.complete_message(message.id, status="interrupted")

    async def _recover(self) -> None:
        worker = self.worker
        state = await worker.state()
        for message in list(state.messages):
            if message.turn_id != self.turn_id or message.finished:
                continue

            if isinstance(message, AssistantMessage):
                stopped = message.model_copy(
                    update={
                        "status": "interrupted",
                        "content": [],
                        "tool_calls": [],
                        "completed_at": time.time(),
                    }
                )
                await worker.append(MessageCompleted(message=stopped, turn_id=self.turn_id))
            elif isinstance(message, ToolResultMessage) and message.status == "in_progress":
                text = strings.NOT_COMPLETED.format(reason=strings.REASON_INTERRUPTED)
                await worker.complete_tool_result(
                    message.id,
                    status="interrupted",
                    content=[TextPart(text=text)],
                    error=text,
                    error_code="interrupted",
                )

    async def _intake(self) -> bool:
        worker = self.worker
        replied = False
        rejection: Deny | None = None
        accepted = 0
        ctx = self.new_context()
        for item in self.items:
            message = item.message.model_copy(update={"turn_id": self.turn_id, "status": "completed"})
            decision = await self.hooks.before("before_turn", ctx, message)
            await worker.dequeue(item)

            if isinstance(decision, Deny):
                rejection = rejection or decision
                continue

            accepted += 1

            if replied:
                await self._add_completed(message if isinstance(decision, Reply) else decision)
                continue

            if isinstance(decision, Reply):
                await self._add_completed(message)
                reply = decision.content
                if not isinstance(reply, (AssistantMessage, CustomMessage)):
                    reply = AssistantMessage(text=str(reply), stop_reason="stop")

                await self._add_completed(reply)
                replied = True
                continue

            await self._add_completed(decision)

        if accepted == 0 and rejection is not None:
            raise TurnRejected(rejection.error_info())
        return replied

    async def _add_completed(self, message: Message) -> None:
        message = message.model_copy(
            update={"turn_id": self.turn_id, "status": "completed", "completed_at": time.time()}
        )
        await self.worker.append(MessageCompleted(message=message, turn_id=self.turn_id))

    async def _add_changed_facts(self) -> None:
        for message in await changed_facts(self.worker, self.turn_id):
            await self._add_completed(message)

    async def _loop(self) -> str:
        worker = self.worker
        agent = worker.agent
        first = True
        while True:
            state = await worker.state()
            pending = state.unfinished_calls(self.turn_id)
            if pending:
                outcome = await ToolStep(self).run(pending)
                first = False

                if outcome == "waiting":
                    return "waiting"
                if outcome == "end":
                    return "completed"
                continue

            if first and self.phase == "recover" and self._already_answered(state):
                return "completed"

            first = False
            turn = state.turns[self.turn_id]
            if agent.max_steps is not None and turn.model_steps >= agent.max_steps:
                raise TurnFailed(
                    ErrorInfo(code="max_steps", message=f"The model has been called {turn.model_steps} times this turn, reaching the max_steps limit")
                )

            message = await ModelStep(self).call()
            if message.tool_calls:
                continue
            if not await self._accept_output(message):
                continue

            decision = await self.hooks.first_result("before_turn_end", self.new_context(), message)
            if isinstance(decision, Continue) and (await worker.state()).turns[self.turn_id].continues < MAX_CONTINUES:
                await self._add_completed(CustomMessage(CONTINUE_KIND, display=False, for_model=decision.prompt))
                continue
            return "completed"

    def _already_answered(self, state: Any) -> bool:
        for message_id in reversed(state.completion_order):
            message = state.by_id[message_id]
            if message.turn_id != self.turn_id:
                continue
            return isinstance(message, AssistantMessage) and message.status == "completed" and not message.tool_calls
        return False

    async def _accept_output(self, message: AssistantMessage) -> bool:
        agent = self.worker.agent
        if agent.output is None:
            return True

        state = await self.worker.state()
        for message_id in state.completion_order:
            item = state.by_id[message_id]
            if (
                item.turn_id == self.turn_id
                and isinstance(item, ToolResultMessage)
                and item.tool_name == SUBMIT_TOOL
                and item.status == "completed"
            ):
                return True

        adapter = TypeAdapter(agent.output)
        if self.native_output:
            try:
                self.native_data = jsonable(adapter.validate_json(message.text))
                self.has_native_data = True
                return True
            except ValidationError as error:
                problem = validation_text(error)
        else:
            problem = strings.SUBMIT_MISSING.format(tool=SUBMIT_TOOL)

        if state.turns[self.turn_id].output_retries >= MAX_OUTPUT_RETRIES:
            raise TurnFailed(
                ErrorInfo(code="invalid_output", message=f"The model didn't give a result that meets the requirements: {problem}", source="model")
            )

        await self._add_completed(
            CustomMessage(OUTPUT_PROBLEM_KIND, display=False, for_model=strings.OUTPUT_PROBLEM.format(problem=problem))
        )
        return False
