from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from typing import Any

from work_agent_sdk.events import (
    MessageCompleted,
    MessageStarted,
    NodeConnected,
    NodeDisconnected,
    RequestClosed,
    RequestOpened,
    SessionDeleted,
    TurnEnded,
    TurnStarted,
)

from openmuse import ui
from openmuse.state import AppState

logger = logging.getLogger("openmuse")

TITLE_PROMPT = "Write a short title for the start of the conversation below, at most 6 words (or 16 characters for Chinese or Japanese). Output only the title itself:\n\n{text}"


class Relay:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.seqs: dict[str, int] = {}
        self._dirty: set[str] = set()
        self.running: dict[str, dict[str, Any]] = {}
        self._listeners: dict[int, set[asyncio.Queue]] = defaultdict(set)
        self._pending_notes: dict[int, set[str]] = defaultdict(set)
        self._flush_scheduled: set[int] = set()
        self._tasks: list[asyncio.Task] = []
        self._chat_users: dict[str, int] = {}

    def start(self) -> None:
        for chat in self.state.db.all_chats():
            self.seqs[chat.id] = chat.last_seq
            self._chat_users[chat.id] = chat.user_id
        self._tasks = [
            asyncio.create_task(self._consume(), name="openmuse:relay"),
            asyncio.create_task(self._save_loop(), name="openmuse:seqs"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._save()

    def _save(self) -> None:
        if not self._dirty:
            return
        seqs = {chat_id: self.seqs[chat_id] for chat_id in self._dirty if chat_id in self.seqs}
        self._dirty.clear()
        self.state.db.save_seqs(seqs)

    async def _save_loop(self) -> None:
        while True:
            await asyncio.sleep(2)
            try:
                self._save()
            except Exception:
                logger.exception("Failed to save event sequence number")

    def subscribe(self, user_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._listeners[user_id].add(queue)
        return queue

    def unsubscribe(self, user_id: int, queue: asyncio.Queue) -> None:
        self._listeners[user_id].discard(queue)

    def notify(self, user_id: int, kind: str) -> None:
        self._pending_notes[user_id].add(kind)
        if user_id in self._flush_scheduled:
            return
        self._flush_scheduled.add(user_id)
        asyncio.get_running_loop().call_later(0.3, self._flush, user_id)

    def _flush(self, user_id: int) -> None:
        self._flush_scheduled.discard(user_id)
        kinds = self._pending_notes.pop(user_id, set())
        for queue in list(self._listeners.get(user_id, ())):
            for kind in sorted(kinds):
                if queue.full():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        queue.get_nowait()
                queue.put_nowait({"type": kind})

    def track_chat(self, chat_id: str, user_id: int) -> None:
        self._chat_users[chat_id] = user_id
        self.seqs.setdefault(chat_id, 0)

    def forget_chat(self, chat_id: str) -> None:
        self._chat_users.pop(chat_id, None)
        self.seqs.pop(chat_id, None)
        self.running.pop(chat_id, None)
        self._dirty.discard(chat_id)

    def last_seq(self, chat_id: str) -> int:
        return self.seqs.get(chat_id, 0)

    def _user_of_device(self, node: str) -> int | None:
        if node.startswith("user-") and node[5:].isdigit():
            return int(node[5:])
        return None

    async def _consume(self) -> None:
        runner = self.state.runner
        assert runner is not None
        async for event in runner.events():
            try:
                self._handle(event)
            except Exception:
                logger.exception("Failed to handle event %s", event.type)

    def _handle(self, event: Any) -> None:
        if isinstance(event, (NodeConnected, NodeDisconnected)):
            user_id = self._user_of_device(event.node)
            if user_id is not None:
                self.notify(user_id, "device")
            return

        chat_id = event.session_id
        if chat_id is None:
            return
        user_id = self._chat_users.get(chat_id)
        if user_id is None:
            return

        if event.seq is not None and event.seq > self.seqs.get(chat_id, 0):
            self.seqs[chat_id] = event.seq
            self._dirty.add(chat_id)

        db = self.state.db
        if isinstance(event, TurnStarted):
            self.running[chat_id] = {
                "turn_id": event.turn_id,
                "source": event.source,
                "started_at": event.ts,
                "step": None,
            }
            if event.turn_id:
                db.start_run(event.turn_id, chat_id, user_id, event.source)
            self.notify(user_id, "activity")

        elif isinstance(event, MessageStarted) and event.message.role == "tool":
            current = self.running.get(chat_id)
            if current is not None:
                current["step"] = event.message.tool_name
            if event.turn_id:
                db.count_step(event.turn_id)
            self.notify(user_id, "activity")

        elif isinstance(event, MessageCompleted):
            message = event.message
            preview = None
            if message.role == "user":
                item = ui.Converter().message(message) or {}
                text = " ".join(ui.strip_notes(message.text).split())
                files = item.get("files") or []
                fallback = files[0].get("name", "File") if files else ("Photo" if item.get("images") else "")
                if text or fallback:
                    preview = "You: " + (text or fallback)
            elif message.role == "assistant" and message.text.strip():
                preview = " ".join(message.text.split())
            elif message.role == "custom" and message.kind == "openmuse.file":
                preview = "Sent a file: " + str((message.data or {}).get("name", ""))
            if preview is not None:
                db.touch_chat(chat_id, preview=preview)
                self.notify(user_id, "chats")

        elif isinstance(event, (RequestOpened, RequestClosed)):
            self.notify(user_id, "activity")

        elif isinstance(event, TurnEnded):
            self.running.pop(chat_id, None)
            result = event.result
            if event.turn_id:
                if result.status == "waiting":
                    db.park_run(event.turn_id)
                else:
                    error = result.error.message if result.error is not None else None
                    db.end_run(event.turn_id, result.status, result.text, error)
            self.notify(user_id, "activity")
            self.notify(user_id, "chats")
            if result.status == "completed":
                chat = db.chat(chat_id)
                if chat is not None and not chat.titled and not chat.hidden:
                    asyncio.create_task(self._make_title(chat_id, user_id, chat.title))

        elif isinstance(event, SessionDeleted):
            self.forget_chat(chat_id)

    async def _make_title(self, chat_id: str, user_id: int, first_text: str) -> None:
        db = self.state.db
        db.rename_chat(chat_id, first_text, titled=True)
        model = self.state.model
        if model is None or not first_text.strip():
            return
        try:
            title = await asyncio.wait_for(model.generate(TITLE_PROMPT.format(text=first_text[:500])), 20)
        except Exception as error:
            logger.info("Failed to generate title: %s", error)
            return
        title = " ".join(str(title).split()).strip("“”\"'《》。.") if title else ""
        if title and db.chat(chat_id) is not None:
            db.rename_chat(chat_id, title[:40], titled=True)
            self.notify(user_id, "chats")
