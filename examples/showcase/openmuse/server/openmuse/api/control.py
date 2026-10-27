from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from openmuse.api.common import utility_chat
from openmuse.auth import websocket_user
from openmuse.nodes import node_of, online
from openmuse.state import app_state


def settings_local() -> bool:
    return app_state().settings.local


logger = logging.getLogger("openmuse")
router = APIRouter()

POINTER = {"left_click", "double_click", "right_click", "mouse_move"}
ACTIONS = POINTER | {"scroll", "type", "key", "navigate"}


class LiveViewError(Exception):
    pass


def _browser_args(action: str, message: dict[str, Any]) -> dict[str, Any]:
    if action in POINTER:
        return {"target": {"type": "coordinate", "x": int(message["x"]), "y": int(message["y"])}}
    if action == "scroll":
        return {
            "target": {"type": "coordinate", "x": int(message["x"]), "y": int(message["y"])},
            "scroll_direction": str(message.get("direction") or "down"),
            "scroll_amount": max(1, min(int(message.get("amount") or 3), 10)),
        }
    if action == "navigate":
        return {"url": str(message["url"])[:2000]}
    return {"text": str(message.get("text") or "")[:2000]}


def _computer_args(action: str, message: dict[str, Any]) -> dict[str, Any]:
    if action in POINTER:
        return {"coordinate": [int(message["x"]), int(message["y"])]}
    if action == "scroll":
        return {
            "coordinate": [int(message["x"]), int(message["y"])],
            "scroll_direction": str(message.get("direction") or "down"),
            "scroll_amount": max(1, min(int(message.get("amount") or 3), 10)),
        }
    return {"text": str(message.get("text") or "")[:2000]}


@router.websocket("/api/control")
async def control(websocket: WebSocket):
    user = await websocket_user(websocket)
    if user is None:
        await websocket.close(code=4401)
        return

    params = websocket.query_params
    target = params.get("target")
    if target not in ("computer", "browser"):
        await websocket.close(code=4400)
        return

    state = app_state()
    runner = state.runner
    assert runner is not None
    chat_id = params.get("chat_id")
    chat = state.db.chat(chat_id) if chat_id else await utility_chat(user)
    if chat is None or chat.user_id != user.id:
        await websocket.close(code=4404)
        return

    session = await runner.session(chat.id)
    request_id = params.get("request_id")
    if request_id:
        pending = {item.id: item for item in await session.pending()}
        request = pending.get(request_id)
        if request is None or request.type != "Takeover" or request.data.get("target") != target:
            await websocket.close(code=4409)
            return

    await websocket.accept()
    if not online(user):
        await websocket.send_json({"type": "closed", "reason": "Your computer is offline"})
        await websocket.close()
        return

    status = (await runner.nodes.status()).get(node_of(user)) or {}
    if (
        not settings_local()
        and status.get("online")
        and not status.get("screen" if target == "computer" else "browser")
    ):
        reason = (
            "Screen control isn't on for this computer. Start the device program in a desktop session "
            "(on a server: Xvfb and DISPLAY=:1)."
            if target == "computer"
            else "The browser isn't on for this computer. Install Chrome or Chromium and restart the device program."
        )
        await websocket.send_json({"type": "closed", "reason": reason})
        await websocket.close()
        return

    resource = await (session.computer() if target == "computer" else session.browser())
    if resource is None:
        await websocket.send_json({"type": "closed", "reason": "Not available in this chat"})
        await websocket.close()
        return

    on_computer = target == "computer"
    to_args = _computer_args if on_computer else _browser_args
    finished = False

    async def push_frames() -> None:
        try:
            await _push_frames()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.info("Live view interrupted: %s", error)
            reason = str(error) if isinstance(error, LiveViewError) else "Lost the live view of your computer"
            with contextlib.suppress(Exception):
                await websocket.send_json({"type": "closed", "reason": reason})
                await websocket.close()

    async def open_tab() -> None:
        context = await resource.browser_context()
        await context.tab(resource.owner)

    async def _push_frames() -> None:
        last_meta = None
        if on_computer:
            frames = resource.watch(max_fps=3, max_size=(1280, 800))
        else:
            try:
                await asyncio.wait_for(open_tab(), 45)
            except TimeoutError:
                raise LiveViewError("The browser didn't start in time. Check the device log.") from None
            except Exception as error:
                logger.warning("Failed to launch browser: %s", error)
                raise LiveViewError("Couldn't start the browser on your computer. Check the device log.") from None
            frames = resource.watch(max_size=(1280, 800), quality=60, max_fps=6)
        frames = frames.__aiter__()
        first = True
        while True:
            try:
                frame = await asyncio.wait_for(frames.__anext__(), 30 if first else 120)
            except StopAsyncIteration:
                return
            except TimeoutError:
                raise LiveViewError("No picture from your computer. Try again.") from None
            first = False
            if on_computer:
                meta = {
                    "type": "frame",
                    "width": frame.width,
                    "height": frame.height,
                    "coord_width": frame.real_width,
                    "coord_height": frame.real_height,
                }
            else:
                meta = {
                    "type": "frame",
                    "width": frame.width,
                    "height": frame.height,
                    "coord_width": frame.viewport_width,
                    "coord_height": frame.viewport_height,
                    "url": frame.url,
                    "title": frame.title,
                }
            if meta != last_meta:
                await websocket.send_json(meta)
                last_meta = meta
            await websocket.send_bytes(frame.image)

    pushing: asyncio.Task | None = None
    try:
        if on_computer:
            await resource.take_control(timeout=60)
        pushing = asyncio.create_task(push_frames())
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")
            if kind == "done":
                finished = True
                break
            if kind == "ping":
                if on_computer:
                    await resource.keep_control()
                continue
            if kind != "input":
                continue
            action = str(message.get("action"))
            if action not in ACTIONS or (on_computer and action == "navigate"):
                await websocket.send_json({"type": "error", "message": f"Unsupported action: {action}"})
                continue
            try:
                await resource.user_input(action, to_args(action, message))
            except (KeyError, TypeError, ValueError) as error:
                await websocket.send_json({"type": "error", "message": f"Invalid input: {error}"})
            except PermissionError as error:
                await websocket.send_json({"type": "error", "message": str(error)})
            except Exception as error:
                logger.info("User action failed: %s", error)
                await websocket.send_json({"type": "error", "message": "That didn't work. Try again."})
    except WebSocketDisconnect:
        pass
    except Exception as error:
        logger.warning("Takeover connection error: %s", error)
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "closed", "reason": "Lost connection to your computer"})
    finally:
        if pushing is not None:
            pushing.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await pushing
        if on_computer:
            with contextlib.suppress(Exception):
                await resource.release_control()

    if finished and request_id:
        with contextlib.suppress(Exception):
            await session.answer(request_id, {"done": True}).queued()
    with contextlib.suppress(Exception):
        await websocket.close()
