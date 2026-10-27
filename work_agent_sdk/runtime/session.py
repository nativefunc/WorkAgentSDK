from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

import work_agent_sdk.runtime.worker.history as history
from work_agent_sdk.core.agent import Agent
from work_agent_sdk.core.errors import ConfigError, RequestClosed
from work_agent_sdk.core.events import (
    Event,
    MessageUpdated,
    ModelCalled,
    SessionStarted,
    TurnEnded,
)
from work_agent_sdk.core.messages import (
    CustomMessage,
    MediaPart,
    Message,
    Usage,
    UserMessage,
    image_mime_type,
)
from work_agent_sdk.core.model import THINKING_LEVELS, ModelCapabilities
from work_agent_sdk.core.requests import PendingRequest
from work_agent_sdk.core.results import SessionInfo, TurnResult
from work_agent_sdk.core.service import UNSET, is_unset
from work_agent_sdk.runtime.trace import build_trace
from work_agent_sdk.runtime.turn.view import model_view
from work_agent_sdk.store import QueueItem

if TYPE_CHECKING:
    from work_agent_sdk.runtime.sessions import Sessions
    from work_agent_sdk.runtime.worker.worker import SessionWorker

MAX_FILE_BYTES = 20 * 1024 * 1024


class TurnHandle:
    """Return value of send() and answer(): await it for the turn's result (when the turn pauses for an answer, the result at the pause), use async for to read the turn's events one by one, and queued() to wait until the message is queued."""

    def __init__(
        self,
        sessions: Sessions,
        target: Callable[[], Awaitable[SessionWorker]],
        perform: Callable[[SessionWorker], Awaitable[tuple[asyncio.Future, str, QueueItem | None]]],
    ) -> None:
        self._sessions = sessions
        self._target = target
        self._perform = perform
        self._started: asyncio.Task | None = None
        self._worker: SessionWorker | None = None
        self._key = ""
        self._item: QueueItem | None = None
        self._future: asyncio.Future | None = None
        self._events: asyncio.Queue | None = None
        self._subscription: Any = None
        self._known_turn: str | None = None
        self.result: TurnResult | None = None

    async def _ensure_submitted(self) -> None:
        if self._started is None:
            self._started = asyncio.ensure_future(self._submit())
        await self._started

    async def _submit(self) -> None:
        worker = await self._target()
        self._worker = worker
        session_id = worker.session_id
        self._subscription = self._sessions.core.bus.subscription(lambda event: event.session_id == session_id)
        self._events = self._subscription.__enter__()
        try:
            self._future, self._key, self._item = await self._perform(worker)
        except BaseException:
            self._unsubscribe()
            raise

        # Handles that only call queued() and are never awaited or iterated (e.g. webhooks): unsubscribe once this segment has a result, to avoid accumulating events
        self._future.add_done_callback(lambda _: self._unsubscribe())

    def _unsubscribe(self) -> None:
        if self._subscription is not None:
            self._subscription.__exit__(None, None, None)
            self._subscription = None

    async def queued(self) -> QueueItem | None:
        """Return as soon as it is queued (for webhooks); the handle can still be awaited afterwards for the result."""
        await self._ensure_submitted()
        return self._item

    def __await__(self) -> Any:
        return self._wait_result().__await__()

    async def _wait_result(self) -> TurnResult:
        await self._ensure_submitted()
        self._unsubscribe()
        assert self._future is not None
        self.result = await self._future
        return self.result

    def __aiter__(self) -> AsyncIterator[Event]:
        return self._follow()

    def _turn_id(self) -> str | None:
        if self._key.startswith("turn:"):
            return self._key[5:]
        if self._known_turn is None and self._item is not None and self._worker is not None:
            self._known_turn = self._worker.item_turn.get(self._item.id)
        if self._known_turn is None and self._future is not None and self._future.done():
            self._known_turn = self._future.result().turn_id or None

        return self._known_turn

    async def _follow(self) -> AsyncIterator[Event]:
        await self._ensure_submitted()
        assert self._future is not None and self._events is not None
        queue = self._events
        try:
            while True:
                getter = asyncio.ensure_future(queue.get())
                await asyncio.wait({getter, self._future}, return_when=asyncio.FIRST_COMPLETED)

                if not getter.done():
                    getter.cancel()
                    # The result is in: output the remaining events of this segment from the queue
                    while not queue.empty():
                        event = queue.get_nowait()
                        if event.turn_id == self._turn_id():
                            yield event
                    break

                event = getter.result()
                turn_id = self._turn_id()
                if turn_id is not None and event.turn_id == turn_id:
                    yield event
                    if isinstance(event, TurnEnded) and (event.result.final or event.result.pending):
                        break
        finally:
            self._unsubscribe()

        self.result = await self._future


class SessionQueue:
    def __init__(self, worker: Callable[[], Awaitable[SessionWorker]]) -> None:
        self._worker = worker

    async def list(self) -> list[QueueItem]:
        return await (await self._worker()).queued_items()

    async def cancel(self, item_id: str) -> bool:
        return await (await self._worker()).cancel_item(item_id)

    async def set_priority(self, item_id: str, priority: int) -> bool:
        return await (await self._worker()).set_priority(item_id, priority)


def _check_images(message: UserMessage, model: ModelCapabilities) -> None:
    limit = model.max_image_bytes
    for part in message.content:
        if isinstance(part, MediaPart) and part.kind == "image" and limit and len(part.data) > limit:
            raise ConfigError(
                f"Image{f' {part.path}' if part.path else ''} is too large: {len(part.data) / 1e6:.1f} MB (base64); "
                f"the limit for model {model.id} is {limit / 1e6:.1f} MB; compress the image first"
            )


def _file_part(path: str) -> MediaPart:
    real = os.path.expanduser(path)
    size = os.path.getsize(real)
    if size > MAX_FILE_BYTES:
        raise ConfigError(f"{path} exceeds the size limit of {MAX_FILE_BYTES // 1024 // 1024} MB")

    with open(real, "rb") as handle:
        data = handle.read()

    if image_mime_type(data) is not None:
        return MediaPart.image_bytes(data, path=path)

    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    kind = mime.split("/")[0] if mime.split("/")[0] in ("audio", "video") else "file"
    return MediaPart(kind=kind, mime=mime, data=base64.b64encode(data).decode(), path=path)


class Session:
    def __init__(self, sessions: Sessions, session_id: str) -> None:
        self._sessions = sessions
        self.id = session_id
        self.queue = SessionQueue(self._worker)

    def __repr__(self) -> str:
        return f"Session({self.id!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Session) and other.id == self.id

    def __hash__(self) -> int:
        return hash(self.id)

    async def _worker(self) -> SessionWorker:
        return await self._sessions.worker(self.id)

    def send(
        self,
        content: str | UserMessage | CustomMessage,
        *,
        files: list[str] | None = None,
        priority: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> TurnHandle:
        async def perform(worker: SessionWorker) -> tuple[asyncio.Future, str, QueueItem | None]:
            if isinstance(content, CustomMessage):
                message: UserMessage | CustomMessage = content.model_copy()
                source = "event"
            else:
                message = UserMessage(text=content) if isinstance(content, str) else content.model_copy()
                source = "user"

                for path in files or []:
                    message.content.append(_file_part(path))

                _check_images(message, worker.model)

            item = QueueItem(
                session_id=worker.session_id, message=message, source=source, priority=priority, metadata=metadata or {}
            )
            key = f"item:{item.id}"
            future = worker.result_future(key)
            await worker.enqueue(item)
            return future, key, item

        return TurnHandle(self._sessions, self._worker, perform)

    def answer(self, request_id: str, value: Any) -> TurnHandle:
        """
        Answer a request in this session or its child sessions. Awaiting gives the result of this session's ongoing turn, the same as send;
        when the request comes from a child session and this session has no turn in progress (e.g. a child session created by the app), it gives the result of that child session's turn.
        """
        owner: list[SessionWorker] = []

        async def target() -> SessionWorker:
            own = await self._worker()
            for session_id in [self.id, *await self._sessions.descendants(self.id)]:
                worker = await self._sessions.worker(session_id)
                if request_id in (await worker.state()).requests:
                    owner.append(worker)
                    turn = (await own.state()).turn
                    if worker is not own and turn is not None and turn.phase in ("running", "parked"):
                        return own
                    return worker

            raise RequestClosed(request_id, "request does not exist")

        async def perform(follow: SessionWorker) -> tuple[asyncio.Future, str, QueueItem | None]:
            worker = owner[0]
            if follow is worker:
                key = f"turn:{(await worker.state()).requests[request_id].turn_id}"
            else:
                turn = (await follow.state()).turn
                assert turn is not None
                key = f"turn:{turn.id}"

            future = await worker.answer(request_id, value, follow=follow, key=key)
            assert future is not None
            return future, key, None

        return TurnHandle(self._sessions, target, perform)

    async def pending(self) -> list[PendingRequest]:
        return await (await self._worker()).pending(children=True)

    async def add_message(self, message: CustomMessage) -> CustomMessage:
        return await (await self._worker()).add_message(message)

    async def update_message(self, message_id: str, *, data: Any = UNSET, display: Any = UNSET) -> None:
        await (await self._worker()).update_message(message_id, data=data, display=display)

    async def complete_message(
        self, message_id: str, *, status: str = "completed", data: Any = UNSET, for_model: Any = UNSET
    ) -> bool:
        return await (await self._worker()).complete_message(
            message_id,
            status=status,
            data=data,
            for_model=for_model,
        )

    async def stop(self, *, everything: bool = False) -> None:
        await (await self._worker()).stop(everything=everything)

    async def close(self, *, outcome: str = "closed") -> None:
        await (await self._worker()).close(outcome=outcome)

    async def delete(self) -> None:
        await self._sessions.delete(await self._worker())

    async def rewind(self, message_id: str) -> list[str]:
        return await history.rewind(await self._worker(), message_id)

    async def fork(self, message_id: str | None = None) -> Session:
        copy = await history.fork(await self._worker(), message_id)
        return Session(self._sessions, copy.session_id)

    async def update(self, *, model: Any = UNSET, thinking: Any = UNSET) -> None:
        """Switch the model or thinking level; passing None restores the Agent's setting. Takes effect from the next model call."""
        worker = await self._worker()
        config = worker.record.config
        if not is_unset(model):
            if model is not None:
                self._sessions.core.model(model)
            config.model = model

        if not is_unset(thinking):
            if thinking is not None and thinking not in THINKING_LEVELS:
                raise ConfigError(f"Invalid thinking value; valid values are {THINKING_LEVELS}")
            config.thinking = thinking

        await worker.save_record()

    async def spawn(self, agent: Agent | str, prompt: str | None = None, *, report: bool = True) -> Session:
        worker = await self._worker()
        child = await self._sessions.tasks.spawn(worker, agent, mode="background" if report else "detached")
        if prompt is not None:
            await self._sessions.tasks.send_prompt(child, prompt)

        return Session(self._sessions, child.session_id)

    async def children(self) -> list[Session]:
        return [Session(self._sessions, child) for child in await self._sessions.children(self.id)]

    async def root(self) -> Session:
        worker = await self._worker()
        return Session(self._sessions, worker.record.root_id)

    async def events(
        self, *, after: int = 0, snapshot: bool = False, children: bool = False, live: bool = True
    ) -> AsyncIterator[Event]:
        """First replay stored events (seq > after), then keep yielding live events; with children=True, includes events from child sessions."""
        worker = await self._worker()
        watched = {self.id}
        if children:
            watched.update(await self._sessions.descendants(self.id))

        def accept(event: Event) -> bool:
            if isinstance(event, SessionStarted) and event.parent_id in watched and children:
                watched.add(event.session_id or "")
            return event.session_id in watched

        bus = self._sessions.core.bus
        with bus.subscription(accept) as queue:
            seen: dict[str, int] = {}
            stored: list[Event] = []
            for session_id in sorted(watched):
                events = await self._sessions.core.store.events(session_id, after=after if session_id == self.id else 0)
                stored.extend(events)
                if events:
                    seen[session_id] = events[-1].seq or 0

            stored.sort(key=lambda event: event.ts)

            for event in stored:
                yield event

            if snapshot:
                for session_id in sorted(watched):
                    target = await self._sessions.worker(session_id)
                    for message in target.snapshot(await target.state()):
                        yield MessageUpdated(
                            session_id=session_id,
                            message_id=message.id,
                            message=message,
                            ephemeral=True,
                            turn_id=message.turn_id,
                        )

            if not live:
                return

            while True:
                event = await queue.get()
                if event.seq is not None and event.seq <= seen.get(event.session_id or "", 0):
                    continue
                yield event

        del worker

    async def history(self, view: str = "raw") -> list[Message]:
        """Return the session history. raw is the visible messages (in start order, with their latest state); model is the view sent to the model."""
        state = await (await self._worker()).state()
        if view == "model":
            return model_view(state)
        if view != "raw":
            raise ConfigError(f'Invalid view value {view!r}; valid values are "raw" or "model"')
        return [message for message in state.messages if message.id not in state.hidden]

    async def usage(self) -> Usage:
        total = Usage()
        for session_id in [self.id, *await self._sessions.descendants(self.id)]:
            for event in await self._sessions.core.store.events(session_id, types={ModelCalled.type}):
                total = total + event.usage
        return total

    async def trace(self, turn_id: str | None = None) -> list[dict[str, Any]]:
        return await build_trace(self._sessions, self.id, turn_id)

    async def info(self) -> SessionInfo:
        return await self._sessions.info(await self._worker())

    async def resource(self, name: str) -> Any:
        return await (await self._worker()).resources.get(name)

    async def workspace(self) -> Any:
        return await self.resource("workspace")

    async def computer(self) -> Any:
        return await self.resource("computer")

    async def browser(self) -> Any:
        return await self.resource("browser")
