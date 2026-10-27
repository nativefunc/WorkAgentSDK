from __future__ import annotations

import asyncio
import json
import logging
from pathlib import PurePosixPath
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from work_agent_sdk import InvalidAnswer, MediaPart, RequestClosed, SessionClosed, TextPart, UserMessage
from work_agent_sdk.core.messages import image_mime_type
from work_agent_sdk.workspace.image_tool import shrink_image

from openmuse import ui
from openmuse.api.common import create_chat, open_session, own_chat, sse, with_heartbeat
from openmuse.auth import CurrentUser
from openmuse.db import Chat, User
from openmuse.files import delete_uploads_of_chat, save_upload, upload_path
from openmuse.nodes import online
from openmuse.state import app_state

logger = logging.getLogger("openmuse")
router = APIRouter(prefix="/api")

EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}


def chat_out(chat: Chat, activity: str = "idle") -> dict[str, Any]:
    return {
        "id": chat.id,
        "title": chat.title,
        "preview": chat.preview,
        "created_at": chat.created_at,
        "updated_at": chat.updated_at,
        "activity": activity,
    }


def _activity(chat_id: str) -> str:
    relay = app_state().relay
    return "running" if relay is not None and chat_id in relay.running else "idle"


@router.get("/chats")
async def list_chats(user: User = CurrentUser):
    return {"chats": [chat_out(chat, _activity(chat.id)) for chat in app_state().db.chats(user.id)]}


class ChatIn(BaseModel):
    title: str = Field(default="New chat", max_length=80)


@router.post("/chats")
async def new_chat(body: ChatIn | None = None, user: User = CurrentUser):
    chat = await create_chat(user, (body.title if body else "New chat").strip() or "New chat")
    return chat_out(chat)


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)


@router.patch("/chats/{chat_id}")
async def rename_chat(chat_id: str, body: RenameIn, user: User = CurrentUser):
    chat = own_chat(user, chat_id)
    app_state().db.rename_chat(chat.id, body.title.strip(), titled=True)
    return chat_out(own_chat(user, chat_id))


@router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str, user: User = CurrentUser):
    chat = own_chat(user, chat_id)
    state = app_state()
    try:
        session = await open_session(chat)
        await session.delete()
    except HTTPException:
        pass
    delete_uploads_of_chat(user.id, chat.id)
    state.db.delete_chat(chat.id)
    if state.relay is not None:
        state.relay.forget_chat(chat.id)
        state.relay.notify(user.id, "activity")
    return {"ok": True}


class MessageIn(BaseModel):
    text: str = Field(default="", max_length=20000)
    attachments: list[str] = Field(default_factory=list, max_length=6)


async def _copy_to_workspace(user: User, chat: Chat, path: str, data: bytes) -> bool:
    state = app_state()
    if not user.settings.get("workspace", True) or state.runner is None:
        return False
    if not online(user):
        return False
    try:
        session = await open_session(chat)
        workspace = await session.workspace()
        await asyncio.wait_for(workspace.files.write(path, data), 30)
        return True
    except Exception as error:
        logger.info("Couldn't put file into the workspace: %s", error)
        return False


def _workspace_name(upload_id: str, name: str) -> str:
    pure = PurePosixPath(name)
    return f"{pure.stem}-{upload_id[-4:]}{pure.suffix}"


def _size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


@router.post("/chats/{chat_id}/messages")
async def post_message(chat_id: str, body: MessageIn, user: User = CurrentUser):
    chat = own_chat(user, chat_id)
    text = body.text.strip()
    if not text and not body.attachments:
        raise HTTPException(400, "Message is empty")

    state = app_state()
    content: list[Any] = [TextPart(text=text)] if text else []
    saved_images: list[str] = []
    files: list[dict[str, Any]] = []
    for upload_id in body.attachments:
        row = state.db.upload(upload_id)
        if row is None or row["user_id"] != user.id:
            raise HTTPException(404, "Attachment not found")
        data = upload_path(user.id, upload_id).read_bytes()
        mime = image_mime_type(data)
        if mime is not None:
            name = upload_id + EXTENSIONS.get(mime, ".img")
            if await _copy_to_workspace(user, chat, f"uploads/{name}", data):
                saved_images.append(f"uploads/{name}")
            content.append(MediaPart.image_bytes(await _for_model(data), path=f"uploads/{name}"))
        else:
            path = f"uploads/{_workspace_name(upload_id, row['name'])}"
            if not await _copy_to_workspace(user, chat, path, data):
                raise HTTPException(
                    409,
                    "Files go into the assistant's workspace, which isn't available right now. "
                    "Check that the workspace is turned on and the computer is online.",
                )
            files.append({"id": upload_id, "name": row["name"], "size": row["size"], "mime": row["mime"], "path": path})
        state.db.attach_upload(upload_id, chat.id)

    notes = []
    if saved_images:
        notes.append("Images saved to the workspace: " + ", ".join(saved_images))
    if files:
        listed = ", ".join(f"{item['path']} ({item['name']}, {_size(item['size'])})" for item in files)
        notes.append(f"Files sent by the user were saved to the workspace: {listed}. Read or process them with commands when needed.")
    if notes:
        content.append(TextPart(text=ui.NOTE_PREFIX + "\n".join(notes)))
    if files:
        public = [{key: item[key] for key in ("id", "name", "size", "mime")} for item in files]
        content.append(TextPart(text=ui.FILES_PREFIX + json.dumps(public, ensure_ascii=False)))

    session = await open_session(chat)
    try:
        item = await session.send(UserMessage(content=content)).queued()
    except SessionClosed:
        raise HTTPException(409, "This chat is closed") from None

    fallback = "Photo" if not files else files[0]["name"]
    if not chat.titled and chat.title in ("New chat", ""):
        state.db.rename_chat(chat.id, (text or fallback)[:40], titled=False)
    state.db.touch_chat(chat.id, preview="You: " + (" ".join(text.split()) if text else fallback))
    return {"ok": True, "queued": item.id if item else None}


@router.post("/chats/{chat_id}/stop")
async def stop_chat(chat_id: str, user: User = CurrentUser):
    session = await open_session(own_chat(user, chat_id))
    await session.stop()
    return {"ok": True}


class AnswerIn(BaseModel):
    value: Any = None


@router.post("/chats/{chat_id}/requests/{request_id}")
async def answer_request(chat_id: str, request_id: str, body: AnswerIn, user: User = CurrentUser):
    session = await open_session(own_chat(user, chat_id))
    if request_id not in {item.id for item in await session.pending()}:
        raise HTTPException(409, "This request has already been answered")
    try:
        await session.answer(request_id, body.value).queued()
    except InvalidAnswer as error:
        raise HTTPException(400, str(error)) from None
    except (RequestClosed, SessionClosed):
        raise HTTPException(409, "This request has already been answered") from None
    return {"ok": True}


@router.get("/chats/{chat_id}/stream")
async def stream_chat(chat_id: str, request: Request, user: User = CurrentUser):
    chat = own_chat(user, chat_id)
    session = await open_session(chat)
    state = app_state()
    assert state.relay is not None
    after = state.relay.last_seq(chat.id)
    converter = ui.Converter()
    messages = [item for item in (converter.message(message) for message in await session.history()) if item]
    for item in messages:
        if item["role"] == "user":
            item["text"] = ui.strip_notes(item["text"])
    requests = [ui.request(item) for item in await session.pending() if item.session_id == chat.id]
    info = await session.info()
    last = state.db.last_run(chat.id)
    error = last["error"] if last is not None and last["status"] == "error" and info.activity != "running" else None

    async def generate():
        yield sse(
            {
                "type": "snapshot",
                "chat": chat_out(chat, info.activity),
                "messages": messages,
                "requests": requests,
                "activity": info.activity,
                "queued": info.queued,
                "error": error,
            }
        )
        async for event in session.events(after=after, snapshot=True):
            for item in converter.events(event):
                if item.get("type") == "message" and item["message"]["role"] == "user":
                    item["message"]["text"] = ui.strip_notes(item["message"]["text"])
                yield sse(item)

    return StreamingResponse(
        with_heartbeat(generate()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _for_model(data: bytes) -> bytes:
    model = app_state().model
    max_edge = getattr(model, "max_image_edge", 2048)
    max_bytes = getattr(model, "max_image_bytes", 5_000_000) * 3 // 4
    try:
        shrunk, _ = await asyncio.to_thread(shrink_image, data, max_edge, max_bytes)
    except ValueError as error:
        raise HTTPException(400, f"Couldn't read this image: {error}") from None
    return shrunk


@router.post("/uploads")
async def upload(file: UploadFile = File(...), user: User = CurrentUser):
    limit = app_state().settings.max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"Files must be under {limit // 1024 // 1024} MB")
    if not data:
        raise HTTPException(400, "The file is empty")
    saved = save_upload(user.id, file.filename or "file", data)
    return {**saved, "url": f"/api/uploads/{saved['id']}"}


@router.get("/uploads/{upload_id}")
async def get_upload(upload_id: str, user: User = CurrentUser):
    row = app_state().db.upload(upload_id)
    if row is None or row["user_id"] != user.id:
        raise HTTPException(404, "File not found")
    path = upload_path(user.id, upload_id)
    if not path.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(
        path,
        media_type=row["mime"],
        filename=row["name"],
        content_disposition_type="inline" if row["mime"].startswith("image/") else "attachment",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
