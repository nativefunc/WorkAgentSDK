from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from work_agent_sdk import Device

from openmuse.auth import EMAIL, CurrentUser, check_password, hash_password, issue_token, request_token, token_digest
from openmuse.db import BOOLEAN_SETTINGS, User
from openmuse.nodes import LOCAL, local_mode, online
from openmuse.state import app_state

router = APIRouter(prefix="/api")

_attempts: dict[str, deque] = defaultdict(deque)


def _throttle(email: str) -> None:
    now = time.time()
    attempts = _attempts[email]
    while attempts and now - attempts[0] > 300:
        attempts.popleft()
    if len(attempts) >= 10:
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    attempts.append(now)


class RegisterIn(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(default="", max_length=60)


class LoginIn(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


def device_summary(user: User) -> dict:
    if local_mode():
        return {"name": LOCAL, "paired": True, "online": online(user), "mode": "local"}
    return {
        "name": user.device,
        "paired": user.device_paired_at is not None,
        "paired_at": user.device_paired_at,
        "online": online(user),
        "mode": "device",
    }


def me(user: User) -> dict:
    return {"user": user.public(), "settings": user.settings, "device": device_summary(user)}


@router.post("/auth/register")
async def register(body: RegisterIn):
    email = body.email.strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(400, "Enter a valid email address")
    state = app_state()
    if state.db.user_by_email(email) is not None:
        raise HTTPException(409, "An account with this email already exists")

    name = body.name.strip() or email.split("@")[0]
    user = state.db.create_user(email, name, hash_password(body.password))
    assert state.runner is not None
    state.runner.nodes.add(Device(user.device, wait=20))
    return {"token": issue_token(user), **me(user)}


@router.post("/auth/login")
async def login(body: LoginIn):
    email = body.email.strip().lower()
    _throttle(email)
    found = app_state().db.user_by_email(email)
    if found is None or not check_password(body.password, found[1]):
        raise HTTPException(401, "Email or password is incorrect")
    _attempts.pop(email, None)
    return {"token": issue_token(found[0]), **me(found[0])}


@router.post("/auth/logout")
async def logout(request: Request, user: User = CurrentUser):
    token = request_token(request)
    if token:
        app_state().db.delete_token(token_digest(token))
    return {"ok": True}


@router.get("/me")
async def get_me(user: User = CurrentUser):
    return me(user)


class SettingsIn(BaseModel):
    workspace: bool | None = None
    browser: bool | None = None
    computer: bool | None = None
    confirm_shell: bool | None = None
    confirm_submit: bool | None = None


@router.patch("/me/settings")
async def update_settings(body: SettingsIn, user: User = CurrentUser):
    changes = {key: value for key, value in body.model_dump().items() if key in BOOLEAN_SETTINGS and value is not None}
    state = app_state()
    updated = state.db.update_settings(user.id, changes)
    if state.relay is not None:
        state.relay.notify(user.id, "device")
    return me(updated)


@router.post("/me/browser/reset")
async def reset_browser(user: User = CurrentUser):
    profile = int(user.settings.get("browser_profile") or 1) + 1
    return me(app_state().db.update_settings(user.id, {"browser_profile": profile}))
