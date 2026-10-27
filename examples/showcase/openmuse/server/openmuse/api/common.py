from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException
from work_agent_sdk import Session

from openmuse.db import Chat, User
from openmuse.resources import session_resources
from openmuse.state import app_state


def own_chat(user: User, chat_id: str) -> Chat:
    chat = app_state().db.chat(chat_id)
    if chat is None or chat.user_id != user.id:
        raise HTTPException(404, "Chat not found")
    return chat


async def open_session(chat: Chat) -> Session:
    runner = app_state().runner
    assert runner is not None
    try:
        return await runner.session(chat.id)
    except KeyError:
        raise HTTPException(404, "Chat not found") from None


async def create_chat(user: User, title: str, *, hidden: bool = False) -> Chat:
    state = app_state()
    assert state.runner is not None and state.relay is not None
    session = await state.runner.new_session(
        "openmuse",
        resources=session_resources(user, state.settings),
        metadata={"user_id": user.id, "node": state.settings.node},
    )
    chat = state.db.add_chat(session.id, user.id, title, hidden=hidden)
    state.relay.track_chat(chat.id, user.id)
    return chat


async def utility_chat(user: User) -> Chat:
    state = app_state()
    db = state.db
    if user.utility_chat:
        chat = db.chat(user.utility_chat)
        if chat is not None:
            session = await open_session(chat)
            info = await session.info()
            if info.metadata.get("node", "device") == state.settings.node:
                return chat
    chat = await create_chat(user, "Remote control", hidden=True)
    db.set_utility_chat(user.id, chat.id)
    return chat


def sse(data: dict[str, Any], event_id: int | None = None) -> str:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}data: {text}\n\n"


async def with_heartbeat(source: AsyncIterator[str], interval: float = 15) -> AsyncIterator[str]:
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    done = object()

    async def pump() -> None:
        try:
            async for item in source:
                await queue.put(item)
        finally:
            await queue.put(done)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), interval)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if item is done:
                break
            yield item
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
