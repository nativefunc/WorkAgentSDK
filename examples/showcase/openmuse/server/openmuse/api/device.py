from __future__ import annotations

import hashlib
import secrets
import shlex
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request, WebSocket
from pydantic import BaseModel, Field
from work_agent_sdk import Device

from openmuse.api.account import device_summary
from openmuse.auth import CurrentUser
from openmuse.db import User
from openmuse.nodes import node_of
from openmuse.state import app_state

router = APIRouter()


def _nodes_url(request: Request) -> str:
    base = app_state().settings.public_url or str(request.base_url).rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    return base.rstrip("/") + "/work_agent_sdk/nodes"


@router.websocket("/work_agent_sdk/nodes")
async def nodes(websocket: WebSocket):
    runner = app_state().runner
    assert runner is not None
    await runner.nodes.websocket(websocket)


@router.get("/api/device")
async def get_device(user: User = CurrentUser):
    runner = app_state().runner
    assert runner is not None
    if app_state().settings.local:
        status = _local_status()
    else:
        status = (await runner.nodes.status()).get(node_of(user)) or {"online": False}
    info = {key: status.get(key) for key in ("online", "os", "screen", "browser", "paused", "last_seen")}
    workspace = status.get("workspace") or {}
    info["workspace_roots"] = workspace.get("roots") if isinstance(workspace, dict) else None
    settings = app_state().settings
    workspace = f"{settings.workspace_path}/{user.device}" if settings.local else settings.workspace_path
    return {**device_summary(user), "info": info, "workspace": workspace}


def _local_status() -> dict:
    import os
    import sys

    from work_agent_sdk.host.browser import find_executable

    screen = sys.platform == "darwin" or bool(os.environ.get("DISPLAY"))
    system = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")
    return {"online": True, "os": system, "screen": screen, "browser": find_executable() is not None}


CODE_TTL = 600
_claims: dict[str, deque] = defaultdict(deque)
_failures: deque = deque()


def _code_digest(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _limit(key: str) -> None:
    now = time.time()
    for queue, limit in ((_claims[key], 10), (_failures, 100)):
        while queue and now - queue[0] > 300:
            queue.popleft()
        if len(queue) >= limit:
            raise HTTPException(429, "Too many attempts. Try again in a few minutes.")


def _http_base(request: Request) -> str:
    return (app_state().settings.public_url or str(request.base_url)).rstrip("/")


@router.post("/api/device/code")
async def pairing_code(request: Request, user: User = CurrentUser):
    state = app_state()
    if state.settings.local:
        raise HTTPException(409, "The workspace, browser and computer run on the server; there is nothing to connect")
    code = f"{secrets.randbelow(1_000_000):06d}"
    issued_at = time.time()
    expires_at = issued_at + CODE_TTL
    state.db.set_pairing_code(user.id, _code_digest(code), expires_at)
    server = _http_base(request)
    return {
        "code": code,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "server": server,
        "command": f"./examples/showcase/openmuse/device/start-device.sh --server {shlex.quote(server)} --code {code}",
    }


class ClaimIn(BaseModel):
    code: str = Field(min_length=6, max_length=12)


@router.post("/api/device/claim")
async def claim_device(body: ClaimIn, request: Request):
    source = request.client.host if request.client else "unknown"
    _limit(source)
    state = app_state()
    runner = state.runner
    assert runner is not None
    user_id = state.db.take_pairing_code(_code_digest(body.code.strip().replace(" ", "")))
    user = state.db.user(user_id) if user_id is not None else None
    if user is None:
        _claims[source].append(time.time())
        _failures.append(time.time())
        raise HTTPException(400, "This code is wrong or has expired. Get a new one in the app.")

    if user.device not in runner.nodes.names():
        runner.nodes.add(Device(user.device, wait=20))
    token = await runner.nodes.issue_token(user.device)
    state.db.set_device_paired(user.id, True)
    if state.relay is not None:
        state.relay.notify(user.id, "device")
    return {"name": user.device, "token": token, "url": _nodes_url(request), "workspace": state.settings.workspace_path}


@router.delete("/api/device")
async def unpair_device(user: User = CurrentUser):
    state = app_state()
    runner = state.runner
    assert runner is not None
    if state.settings.local:
        raise HTTPException(
            409, "The workspace, browser and computer run on the server; there is nothing to disconnect"
        )
    await runner.nodes.revoke(user.device)
    state.db.set_device_paired(user.id, False)
    if state.relay is not None:
        state.relay.notify(user.id, "device")
    return {"ok": True}
