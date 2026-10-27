from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from work_agent_sdk import ScheduleService

from openmuse import ui
from openmuse.api.common import create_chat, open_session, own_chat, sse, with_heartbeat
from openmuse.auth import CurrentUser
from openmuse.db import User
from openmuse.state import app_state

router = APIRouter(prefix="/api")


def _schedule_out(record, title: str) -> dict:
    return {
        "id": record.id,
        "chat_id": record.session_id,
        "chat_title": title,
        "prompt": record.prompt,
        "kind": record.kind,
        "at": record.at,
        "every_minutes": record.every_minutes,
        "daily": record.daily,
        "weekdays": record.weekdays,
        "timezone": record.timezone,
        "next_run": record.next_run,
        "last_run": record.last_run,
        "paused": record.paused,
        "created_at": record.created_at,
    }


@router.get("/activity")
async def activity(user: User = CurrentUser):
    state = app_state()
    runner = state.runner
    relay = state.relay
    assert runner is not None and relay is not None
    chats = {chat.id: chat for chat in state.db.chats(user.id)}

    async def pending_of(chat_id: str) -> list:
        try:
            session = await runner.session(chat_id)
            return await session.pending()
        except KeyError:
            return []

    needs_you = []
    results = await asyncio.gather(*(pending_of(chat_id) for chat_id in chats))
    for chat_id, pending in zip(chats, results, strict=True):
        for item in pending:
            if item.answered_by != "user":
                continue
            needs_you.append({"chat_id": chat_id, "chat_title": chats[chat_id].title, "request": ui.request(item)})
    needs_you.sort(key=lambda entry: entry["request"]["created_at"], reverse=True)

    running = [
        {
            "chat_id": chat_id,
            "chat_title": chats[chat_id].title,
            "turn_id": current["turn_id"],
            "source": current["source"],
            "started_at": current["started_at"],
            "step": current["step"],
        }
        for chat_id, current in relay.running.items()
        if chat_id in chats and (current["source"] == "schedule" or current["step"] is not None)
    ]

    schedules = runner.service(ScheduleService)
    scheduled = [
        _schedule_out(record, chats[record.session_id].title)
        for record in await schedules.list()
        if record.session_id in chats
    ]

    recent = [
        {
            "turn_id": row["turn_id"],
            "chat_id": row["chat_id"],
            "chat_title": row["chat_title"],
            "source": row["source"],
            "status": row["status"],
            "summary": row["summary"],
            "steps": row["steps"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
        }
        for row in state.db.runs(user.id)
        if row["source"] == "schedule" or row["steps"] > 0
    ]
    return {"needs_you": needs_you, "running": running, "scheduled": scheduled, "recent": recent}


async def _own_schedule(user: User, schedule_id: str):
    schedules = app_state().runner.service(ScheduleService)
    try:
        record = await schedules.get(schedule_id)
    except LookupError:
        raise HTTPException(404, "Routine not found") from None
    own_chat(user, record.session_id)
    return schedules, record


@router.post("/schedules/{schedule_id}/{action}")
async def schedule_action(schedule_id: str, action: Literal["pause", "resume", "run"], user: User = CurrentUser):
    schedules, record = await _own_schedule(user, schedule_id)
    if action == "pause":
        await schedules.pause(record.id)
    elif action == "resume":
        await schedules.resume(record.id)
    else:
        await schedules.run_now(record.id)
    app_state().relay.notify(user.id, "activity")
    return {"ok": True}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, user: User = CurrentUser):
    schedules, record = await _own_schedule(user, schedule_id)
    await schedules.delete(record.id)
    app_state().relay.notify(user.id, "activity")
    return {"ok": True}


class RoutineIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    repeat: Literal["once", "daily", "weekdays", "weekly", "hourly"] = "daily"
    time: str = Field(default="09:00", pattern=r"^\d{1,2}:\d{2}$")
    date: str | None = Field(default=None, description="Date when repeat=once, YYYY-MM-DD")
    weekday: int = Field(default=1, ge=1, le=7)


@router.post("/routines")
async def create_routine(body: RoutineIn, user: User = CurrentUser):
    state = app_state()
    schedules = state.runner.service(ScheduleService)
    title = " ".join(body.prompt.split())[:40]
    chat = await create_chat(user, title)
    state.db.rename_chat(chat.id, title, titled=True)
    hour, minute = (int(part) for part in body.time.split(":"))
    daily = f"{hour:02d}:{minute:02d}"
    tz = state.settings.timezone
    try:
        if body.repeat == "once":
            if not body.date:
                raise HTTPException(400, "Pick a date")
            record = await schedules.create(chat.id, body.prompt, at=f"{body.date}T{daily}", timezone=tz)
        elif body.repeat == "hourly":
            record = await schedules.create(chat.id, body.prompt, every_minutes=60, timezone=tz)
        elif body.repeat == "weekdays":
            record = await schedules.create(chat.id, body.prompt, daily=daily, weekdays=[1, 2, 3, 4, 5], timezone=tz)
        elif body.repeat == "weekly":
            record = await schedules.create(chat.id, body.prompt, daily=daily, weekdays=[body.weekday], timezone=tz)
        else:
            record = await schedules.create(chat.id, body.prompt, daily=daily, timezone=tz)
    except ValueError as error:
        session = await open_session(chat)
        await session.delete()
        state.db.delete_chat(chat.id)
        raise HTTPException(400, str(error)) from None

    state.relay.notify(user.id, "activity")
    state.relay.notify(user.id, "chats")
    return _schedule_out(record, title)


@router.get("/events")
async def user_events(user: User = CurrentUser):
    relay = app_state().relay
    assert relay is not None
    queue = relay.subscribe(user.id)

    async def generate():
        try:
            yield sse({"type": "hello"})
            while True:
                yield sse(await queue.get())
        finally:
            relay.unsubscribe(user.id, queue)

    return StreamingResponse(
        with_heartbeat(generate()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
