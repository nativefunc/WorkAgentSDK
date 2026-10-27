from __future__ import annotations

import mimetypes
import re
import secrets
from pathlib import Path

from work_agent_sdk.core.messages import image_mime_type

from openmuse.state import app_state

UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def safe_name(name: str) -> str:
    name = UNSAFE_NAME.sub("_", Path(name.replace("\\", "/")).name).strip(" .") or "file"
    if len(name) > 80:
        stem, dot, suffix = name.rpartition(".")
        name = (stem[: 79 - len(suffix)] + "." + suffix) if dot and len(suffix) <= 10 else name[:80]
    return name


def guess_mime(name: str, data: bytes) -> str:
    return image_mime_type(data) or mimetypes.guess_type(name)[0] or "application/octet-stream"


def upload_path(user_id: int, upload_id: str) -> Path:
    return app_state().settings.uploads_dir / str(user_id) / upload_id


def save_upload(user_id: int, name: str, data: bytes, *, chat_id: str | None = None, mime: str | None = None) -> dict:
    upload_id = "up_" + secrets.token_hex(12)
    path = upload_path(user_id, upload_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    name = safe_name(name)
    mime = mime or guess_mime(name, data)
    app_state().db.add_upload(upload_id, user_id, name, mime, len(data), chat_id)
    return {"id": upload_id, "name": name, "mime": mime, "size": len(data)}


def delete_uploads_of_chat(user_id: int, chat_id: str) -> None:
    db = app_state().db
    for row in db.uploads_of_chat(chat_id):
        upload_path(user_id, row["id"]).unlink(missing_ok=True)
    db.delete_uploads_of_chat(chat_id)
