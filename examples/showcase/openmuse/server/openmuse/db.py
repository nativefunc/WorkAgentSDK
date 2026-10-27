from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    password TEXT NOT NULL,
    created_at REAL NOT NULL,
    settings TEXT NOT NULL DEFAULT '{}',
    device_paired_at REAL,
    utility_chat TEXT
);
CREATE TABLE IF NOT EXISTS tokens (
    digest TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    last_used REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    preview TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_seq INTEGER NOT NULL DEFAULT 0,
    titled INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS chats_user ON chats (user_id, updated_at);
CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    chat_id TEXT,
    name TEXT NOT NULL,
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    turn_id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    error TEXT,
    steps INTEGER NOT NULL DEFAULT 0,
    started_at REAL NOT NULL,
    ended_at REAL
);
CREATE INDEX IF NOT EXISTS runs_user ON runs (user_id, started_at);
CREATE TABLE IF NOT EXISTS pairing_codes (
    digest TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at REAL NOT NULL
);
"""

DEFAULT_SETTINGS: dict[str, Any] = {
    "workspace": True,
    "browser": True,
    "computer": True,
    "confirm_shell": False,
    "confirm_submit": True,
    "browser_profile": 1,
}
BOOLEAN_SETTINGS = ("workspace", "browser", "computer", "confirm_shell", "confirm_submit")


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str
    created_at: float
    settings: dict[str, Any]
    device_paired_at: float | None
    utility_chat: str | None

    @property
    def device(self) -> str:
        return f"user-{self.id}"

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "email": self.email, "name": self.name, "created_at": self.created_at}


@dataclass(frozen=True)
class Chat:
    id: str
    user_id: int
    title: str
    preview: str
    created_at: float
    updated_at: float
    last_seq: int
    titled: bool
    hidden: bool


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _all(self, sql: str, *args: Any) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _one(self, sql: str, *args: Any) -> sqlite3.Row | None:
        with self._lock:
            return self._db.execute(sql, args).fetchone()

    def _run(self, sql: str, *args: Any) -> int:
        with self._lock:
            cursor = self._db.execute(sql, args)
            return cursor.lastrowid if cursor.lastrowid is not None else cursor.rowcount

    @staticmethod
    def _user(row: sqlite3.Row | None) -> User | None:
        if row is None:
            return None
        settings = {**DEFAULT_SETTINGS, **json.loads(row["settings"] or "{}")}
        return User(
            id=row["id"],
            email=row["email"],
            name=row["name"],
            created_at=row["created_at"],
            settings=settings,
            device_paired_at=row["device_paired_at"],
            utility_chat=row["utility_chat"],
        )

    def create_user(self, email: str, name: str, password_hash: str) -> User:
        user_id = self._run(
            "INSERT INTO users (email, name, password, created_at) VALUES (?, ?, ?, ?)",
            email,
            name,
            password_hash,
            time.time(),
        )
        user = self.user(user_id)
        assert user is not None
        return user

    def user(self, user_id: int) -> User | None:
        return self._user(self._one("SELECT * FROM users WHERE id = ?", user_id))

    def user_by_email(self, email: str) -> tuple[User, str] | None:
        row = self._one("SELECT * FROM users WHERE email = ?", email)
        if row is None:
            return None
        user = self._user(row)
        assert user is not None
        return user, row["password"]

    def users(self) -> list[User]:
        return [user for row in self._all("SELECT * FROM users") if (user := self._user(row)) is not None]

    def update_settings(self, user_id: int, changes: dict[str, Any]) -> User:
        user = self.user(user_id)
        assert user is not None
        settings = {**user.settings, **changes}
        self._run("UPDATE users SET settings = ? WHERE id = ?", json.dumps(settings), user_id)
        updated = self.user(user_id)
        assert updated is not None
        return updated

    def set_device_paired(self, user_id: int, paired: bool) -> None:
        self._run("UPDATE users SET device_paired_at = ? WHERE id = ?", time.time() if paired else None, user_id)

    def set_pairing_code(self, user_id: int, digest: str, expires_at: float) -> None:
        self._run("DELETE FROM pairing_codes WHERE user_id = ? OR expires_at < ?", user_id, time.time())
        self._run(
            "INSERT INTO pairing_codes (digest, user_id, expires_at) VALUES (?, ?, ?)", digest, user_id, expires_at
        )

    def take_pairing_code(self, digest: str) -> int | None:
        rows = self._all("SELECT user_id FROM pairing_codes WHERE digest = ? AND expires_at >= ?", digest, time.time())
        self._run("DELETE FROM pairing_codes WHERE digest = ?", digest)
        return int(rows[0]["user_id"]) if rows else None

    def set_utility_chat(self, user_id: int, chat_id: str) -> None:
        self._run("UPDATE users SET utility_chat = ? WHERE id = ?", chat_id, user_id)

    def add_token(self, digest: str, user_id: int) -> None:
        now = time.time()
        self._run(
            "INSERT INTO tokens (digest, user_id, created_at, last_used) VALUES (?, ?, ?, ?)", digest, user_id, now, now
        )

    def token_user(self, digest: str) -> int | None:
        row = self._one("SELECT user_id, last_used FROM tokens WHERE digest = ?", digest)
        if row is None:
            return None
        if time.time() - row["last_used"] > 3600:
            self._run("UPDATE tokens SET last_used = ? WHERE digest = ?", time.time(), digest)
        return int(row["user_id"])

    def delete_token(self, digest: str) -> None:
        self._run("DELETE FROM tokens WHERE digest = ?", digest)

    @staticmethod
    def _chat(row: sqlite3.Row | None) -> Chat | None:
        if row is None:
            return None
        return Chat(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            preview=row["preview"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_seq=row["last_seq"],
            titled=bool(row["titled"]),
            hidden=bool(row["hidden"]),
        )

    def add_chat(self, chat_id: str, user_id: int, title: str, *, hidden: bool = False) -> Chat:
        now = time.time()
        self._run(
            "INSERT INTO chats (id, user_id, title, created_at, updated_at, hidden) VALUES (?, ?, ?, ?, ?, ?)",
            chat_id,
            user_id,
            title,
            now,
            now,
            int(hidden),
        )
        chat = self.chat(chat_id)
        assert chat is not None
        return chat

    def chat(self, chat_id: str) -> Chat | None:
        return self._chat(self._one("SELECT * FROM chats WHERE id = ?", chat_id))

    def chats(self, user_id: int) -> list[Chat]:
        rows = self._all("SELECT * FROM chats WHERE user_id = ? AND hidden = 0 ORDER BY updated_at DESC", user_id)
        return [chat for row in rows if (chat := self._chat(row)) is not None]

    def all_chats(self) -> list[Chat]:
        return [chat for row in self._all("SELECT * FROM chats") if (chat := self._chat(row)) is not None]

    def touch_chat(self, chat_id: str, *, preview: str | None = None) -> None:
        if preview is None:
            self._run("UPDATE chats SET updated_at = ? WHERE id = ?", time.time(), chat_id)
        else:
            self._run("UPDATE chats SET updated_at = ?, preview = ? WHERE id = ?", time.time(), preview[:200], chat_id)

    def rename_chat(self, chat_id: str, title: str, *, titled: bool = True) -> None:
        self._run("UPDATE chats SET title = ?, titled = ? WHERE id = ?", title, int(titled), chat_id)

    def save_seqs(self, seqs: dict[str, int]) -> None:
        with self._lock:
            self._db.executemany(
                "UPDATE chats SET last_seq = MAX(last_seq, ?) WHERE id = ?",
                [(seq, chat_id) for chat_id, seq in seqs.items()],
            )

    def delete_chat(self, chat_id: str) -> None:
        self._run("DELETE FROM chats WHERE id = ?", chat_id)
        self._run("DELETE FROM runs WHERE chat_id = ?", chat_id)

    def add_upload(
        self, upload_id: str, user_id: int, name: str, mime: str, size: int, chat_id: str | None = None
    ) -> None:
        self._run(
            "INSERT INTO uploads (id, user_id, chat_id, name, mime, size, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            upload_id,
            user_id,
            chat_id,
            name,
            mime,
            size,
            time.time(),
        )

    def upload(self, upload_id: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM uploads WHERE id = ?", upload_id)

    def attach_upload(self, upload_id: str, chat_id: str) -> None:
        self._run("UPDATE uploads SET chat_id = ? WHERE id = ? AND chat_id IS NULL", chat_id, upload_id)

    def uploads_of_chat(self, chat_id: str) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM uploads WHERE chat_id = ?", chat_id)

    def delete_uploads_of_chat(self, chat_id: str) -> None:
        self._run("DELETE FROM uploads WHERE chat_id = ?", chat_id)

    def start_run(self, turn_id: str, chat_id: str, user_id: int, source: str) -> None:
        self._run(
            "INSERT INTO runs (turn_id, chat_id, user_id, source, status, started_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (turn_id) DO UPDATE SET status = 'running', ended_at = NULL",
            turn_id,
            chat_id,
            user_id,
            source,
            "running",
            time.time(),
        )

    def count_step(self, turn_id: str) -> None:
        self._run("UPDATE runs SET steps = steps + 1 WHERE turn_id = ?", turn_id)

    def park_run(self, turn_id: str) -> None:
        self._run("UPDATE runs SET status = 'waiting' WHERE turn_id = ?", turn_id)

    def end_run(self, turn_id: str, status: str, summary: str, error: str | None) -> None:
        self._run(
            "UPDATE runs SET status = ?, summary = ?, error = ?, ended_at = ? WHERE turn_id = ?",
            status,
            summary[:500],
            error,
            time.time(),
            turn_id,
        )

    def last_run(self, chat_id: str) -> sqlite3.Row | None:
        rows = self._all("SELECT * FROM runs WHERE chat_id = ? ORDER BY started_at DESC LIMIT 1", chat_id)
        return rows[0] if rows else None

    def runs(self, user_id: int, limit: int = 60) -> list[sqlite3.Row]:
        return self._all(
            "SELECT runs.*, chats.title AS chat_title FROM runs JOIN chats ON chats.id = runs.chat_id "
            "WHERE runs.user_id = ? AND runs.ended_at IS NOT NULL AND chats.hidden = 0 "
            "ORDER BY runs.started_at DESC LIMIT ?",
            user_id,
            limit,
        )

    def interrupt_running(self) -> None:
        self._run("UPDATE runs SET status = 'interrupted', ended_at = ? WHERE status = 'running'", time.time())
