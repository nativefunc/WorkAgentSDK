from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import work_agent_sdk.strings.runtime as strings
from work_agent_sdk.core.messages import CustomMessage
from work_agent_sdk.runtime.context import jsonable

if TYPE_CHECKING:
    from work_agent_sdk.runtime.worker.worker import SessionWorker

logger = logging.getLogger("work_agent_sdk")


async def changed_facts(worker: SessionWorker, turn_id: str) -> list[CustomMessage]:
    state = await worker.state()
    messages: list[CustomMessage] = []
    ref = await worker.session_ref()
    for name in worker.resources.names():
        provider = worker.core.provider(name)
        if provider is None:
            continue

        try:
            facts = jsonable(await provider.facts(ref))
        except Exception:
            logger.exception("获取资源 %s 的 facts 时出错", name)
            continue

        if facts is None:
            continue

        kind = f"context.{name}"
        last = state.last_context(kind)
        if last is not None and last.data == facts:
            continue

        messages.append(
            CustomMessage(kind, data=facts, display=False, for_model=provider.render(facts), turn_id=turn_id)
        )

    sources = await tool_sources(worker)
    kind = "context.tools"
    last = state.last_context(kind)
    if (last is None and sources) or (last is not None and last.data != sources):
        lines = "\n".join(f"- {item['name']}：{item['description']}" for item in sources)
        text = strings.TOOLS_SOURCES.format(sources=lines) if sources else strings.TOOLS_SOURCES_EMPTY
        messages.append(CustomMessage(kind, data=sources, display=False, for_model=text, turn_id=turn_id))

    return messages


async def tool_sources(worker: SessionWorker) -> list[dict[str, Any]]:
    if not worker.model.tool_search:
        return []

    extensions = worker.core.extensions()
    return [{"name": item.name, "description": item.description or ""} for item in extensions]
