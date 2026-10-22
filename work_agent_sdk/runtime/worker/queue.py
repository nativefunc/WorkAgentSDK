from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from work_agent_sdk.core.utils import new_id
from work_agent_sdk.store import QueueItem

if TYPE_CHECKING:
    from work_agent_sdk.runtime.worker.worker import SessionWorker


@dataclass
class NextSegment:
    turn_id: str
    phase: str  # new / resume / recover
    items: list[QueueItem] = field(default_factory=list)


async def next_segment(worker: SessionWorker) -> NextSegment | None:
    state = await worker.state()
    turn = state.turn

    # 记录中有一轮处于运行状态，但本进程并未运行它（上次停机时正在运行）：恢复该轮
    if turn is not None and turn.phase == "running":
        return NextSegment(turn.id, "recover")

    items = await worker.queued_items()

    if turn is not None and turn.phase == "parked":
        waiting = state.waiting_calls(turn.id)
        if not waiting or any(state.resumable(call) for call in waiting):
            return NextSegment(turn.id, "resume")
        if items and items[0].from_user and await worker.waiting_on_user(turn.id):
            # 用户未答复请求而发送了新消息：作废该轮，然后处理新消息
            await worker.end_parked("cancelled")
        else:
            return None

    if not items:
        return None

    if items[0].from_user:
        batch = [items[0]]
    else:
        batch = []
        for item in items:
            if item.from_user:
                break
            batch.append(item)

    return NextSegment(new_id("turn_"), "new", batch)
