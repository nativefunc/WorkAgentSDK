from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import jsonschema
from pydantic import ValidationError

import work_agent_sdk.strings.runtime as strings
from work_agent_sdk.core.errors import InvalidAnswer, RequestClosed, ToolError
from work_agent_sdk.core.events import RequestClosed as RequestClosedEvent
from work_agent_sdk.core.events import RequestOpened
from work_agent_sdk.core.requests import PendingRequest, Request
from work_agent_sdk.core.utils import new_id
from work_agent_sdk.runtime.context import jsonable

if TYPE_CHECKING:
    from work_agent_sdk.runtime.context import RunContext
    from work_agent_sdk.runtime.worker.state import RequestState
    from work_agent_sdk.runtime.worker.worker import SessionWorker


class Requests:
    def __init__(self, worker: SessionWorker) -> None:
        self.worker = worker
        # Answers to sensitive requests: request id -> (owning call id, answer)
        self._sensitive_answers: dict[str, tuple[str | None, Any]] = {}

    async def open(self, ctx: RunContext, request: Request, ordinal: int) -> str:
        pending = PendingRequest(
            id=new_id("req_"),
            type=request.type_name(),
            data=request.data(),
            answer_schema=request.answer_schema(),
            answered_by=type(request).answered_by,
            sensitive=request.sensitive(),
            session_id=self.worker.session_id,
            agent=self.worker.record.agent,
            call_id=ctx.call.id if ctx.call else None,
            created_at=time.time(),
        )

        # Don't notify the parent here: once this segment settles (all concurrent calls finished or paused), SessionWorker tells the waiting handles together
        await self.worker.append(RequestOpened(request=pending, ordinal=ordinal, turn_id=ctx.turn_id))
        return pending.id

    async def answer(self, request_id: str, value: Any) -> None:
        state = await self.worker.state()
        request = state.requests.get(request_id)
        if request is None:
            raise RequestClosed(request_id, "request does not exist")
        if not request.pending:
            raise RequestClosed(request_id, request.status)

        value = jsonable(value)
        if request.answer_schema:
            try:
                jsonschema.validate(value, request.answer_schema)
            except jsonschema.ValidationError as error:
                where = ".".join(str(step) for step in error.absolute_path) or "answer"
                # Errors for sensitive requests don't include the input value
                problem = f"fails the {error.validator} constraint" if request.sensitive else error.message
                raise InvalidAnswer(f"{where}: {problem}") from None
            except jsonschema.SchemaError:
                pass

        if request.sensitive:
            self._sensitive_answers[request_id] = (request.call_id, value)

        await self.worker.append(
            RequestClosedEvent(
                request_id=request_id,
                call_id=request.call_id,
                status="answered",
                answer=None if request.sensitive else value,
                turn_id=request.turn_id,
            )
        )

    async def close(self, request: RequestState, status: str) -> None:
        if not request.pending:
            return
        await self.worker.append(
            RequestClosedEvent(
                request_id=request.id,
                call_id=request.call_id,
                status=status,
                turn_id=request.turn_id,
            )
        )

    async def resolve(self, recorded: RequestState, request: Request) -> Any:
        if recorded.sensitive:
            found = self._sensitive_answers.get(recorded.id)
            if found is None:
                raise ToolError(strings.SENSITIVE_ANSWER_LOST, code="answer_lost")
            value = found[1]
        else:
            value = recorded.answer

        try:
            return request.parse_answer(value)
        except ValidationError as error:
            problems = []
            for item in error.errors(include_input=False):
                field = ".".join(str(step) for step in item["loc"]) or "answer"
                problems.append(f"{field}: {item['msg']}")
            raise ToolError(strings.ANSWER_INVALID.format(problem="; ".join(problems)), code="invalid_answer") from None
        except Exception as error:
            problem = type(error).__name__ if recorded.sensitive else str(error)
            raise ToolError(strings.ANSWER_INVALID.format(problem=problem), code="invalid_answer") from None

    def forget_call(self, call_id: str) -> None:
        for request_id in [key for key, (owner, _) in self._sensitive_answers.items() if owner == call_id]:
            del self._sensitive_answers[request_id]

    def forget_all(self) -> None:
        self._sensitive_answers.clear()
