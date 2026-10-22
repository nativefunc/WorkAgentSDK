from __future__ import annotations

from typing import TYPE_CHECKING

from work_agent_sdk.core.errors import ConfigError
from work_agent_sdk.core.events import MessageCompleted, SessionRewound
from work_agent_sdk.core.messages import UserMessage

if TYPE_CHECKING:
    from work_agent_sdk.runtime.worker.worker import SessionWorker


def _top_level(worker: SessionWorker, what: str) -> None:
    if worker.record.parent_id is not None:
        raise ConfigError(f"{what}仅适用于顶层会话；子会话的记录由上级会话驱动")


async def rewind(worker: SessionWorker, message_id: str) -> list[str]:
    _top_level(worker, "回退")
    state = await worker.state()
    target = state.message(message_id)
    if not isinstance(target, UserMessage) or message_id in state.hidden:
        raise ConfigError(f"{message_id} 不是可见的用户消息")

    await worker.stop()

    async with worker.hold_segments():
        state = await worker.state()
        index = next(i for i, message in enumerate(state.messages) if message.id == message_id)
        hidden = [message.id for message in state.messages[index:] if message.id not in state.hidden]
        await worker.append(SessionRewound(message_id=message_id, hidden=hidden))

    return hidden


async def fork(worker: SessionWorker, message_id: str | None = None) -> SessionWorker:
    _top_level(worker, "复制")
    state = await worker.state()
    limit: int | None = None
    if message_id is not None:
        target = state.message(message_id)
        if not isinstance(target, UserMessage) or message_id in state.hidden:
            raise ConfigError(f"{message_id} 不是可见的用户消息")
        limit = next(i for i, message in enumerate(state.messages) if message.id == message_id)

    allowed = {
        message.id
        for index, message in enumerate(state.messages)
        if (limit is None or index < limit) and message.id not in state.hidden and message.finished
    }
    config = worker.record.config.model_copy(deep=True)
    config.forked_from = worker.session_id
    config.task = None
    copy = await worker.sessions.create(worker.record.agent, config)
    for copied_id in state.completion_order:
        if copied_id in allowed:
            message = state.by_id[copied_id]
            await copy.append(MessageCompleted(message=message, turn_id=message.turn_id))

    return copy
