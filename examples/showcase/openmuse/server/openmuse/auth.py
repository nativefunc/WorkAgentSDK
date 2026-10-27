from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

from fastapi import Depends, HTTPException, Request, WebSocket, status

from openmuse.db import User
from openmuse.state import app_state

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), **SCRYPT)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(user: User) -> str:
    token = "om_" + secrets.token_urlsafe(32)
    app_state().db.add_token(token_digest(token), user.id)
    return token


def _token_from(headers: dict, query: dict) -> str | None:
    header = headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return query.get("token")


def user_for_token(token: str | None) -> User | None:
    if not token:
        return None
    state = app_state()
    user_id = state.db.token_user(token_digest(token))
    return state.db.user(user_id) if user_id is not None else None


async def current_user(request: Request) -> User:
    user = user_for_token(_token_from(dict(request.headers), dict(request.query_params)))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in again")
    return user


async def websocket_user(websocket: WebSocket) -> User | None:
    return user_for_token(_token_from(dict(websocket.headers), dict(websocket.query_params)))


def request_token(request: Request) -> str | None:
    return _token_from(dict(request.headers), dict(request.query_params))


CurrentUser = Depends(current_user)
