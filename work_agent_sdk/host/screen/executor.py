from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import logging
import time
from collections.abc import Callable
from typing import Any

from work_agent_sdk.host.screen.actions import ACTIONS, KEYBOARD, is_input
from work_agent_sdk.host.screen.apps import (
    OPEN_TIMEOUT,
    AppsBackend,
    find_app,
    public,
    same_app,
)
from work_agent_sdk.host.screen.backends import ScreenBackend
from work_agent_sdk.host.screen.policy import (
    ComputerPolicy,
    DeviceCeiling,
    ceiling_check,
    ceiling_check_open,
    check,
    check_open,
    safe_app_name,
)

logger = logging.getLogger("work_agent_sdk")

# An Esc received within this time after the framework itself sends keys is treated as coming from the framework, not pressed by the user
OWN_INPUT_WINDOW = 0.5
# Screenshots are compressed to JPEG on the executor before transfer, about 1/5 to 1/10 the size of a PNG of the same dimensions
SCREENSHOT_QUALITY = 75


def fit_within(size: tuple[int, int], limit: tuple[int, int]) -> tuple[int, int]:
    width, height = size
    ratio = min(1.0, limit[0] / width, limit[1] / height)
    return max(1, round(width * ratio)), max(1, round(height * ratio))


def capture(png: bytes, max_size: tuple[int, int] | None, region: tuple[int, int, int, int] | None) -> dict[str, Any]:
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("Screen control requires Pillow; run pip install Pillow pyautogui") from None

    import io

    with Image.open(io.BytesIO(png)) as image:
        real = image.size
        picture = image
        if region is not None:
            x0, y0, x1, y1 = (int(value) for value in region)
            x0, x1 = sorted((max(0, min(x0, real[0])), max(0, min(x1, real[0]))))
            y0, y1 = sorted((max(0, min(y0, real[1])), max(0, min(y1, real[1]))))
            if x1 - x0 < 1 or y1 - y0 < 1:
                raise ValueError("The region given to zoom is empty")

            picture = image.crop((x0, y0, x1, y1))

        size = fit_within(picture.size, (int(max_size[0]), int(max_size[1]))) if max_size else picture.size
        if size != picture.size:
            picture = picture.resize(size, Image.LANCZOS)

        buffer = io.BytesIO()
        picture.convert("RGB").save(
            buffer,
            format="JPEG",
            quality=SCREENSHOT_QUALITY,
            optimize=True,
        )
        data = buffer.getvalue()

    return {
        "image": base64.b64encode(data).decode(),
        "width": size[0],
        "height": size[1],
        "real_width": real[0],
        "real_height": real[1],
        "mime": "image/jpeg",
    }


class ScreenExecutor:
    def __init__(
        self,
        backend: ScreenBackend,
        apps: AppsBackend,
        *,
        ceiling: DeviceCeiling | None = None,
        on_activity: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self.backend = backend
        self.apps = apps
        self.ceiling = ceiling
        self.on_activity = on_activity
        self.paused: str | None = None
        self._lock = asyncio.Lock()
        self._current: asyncio.Task | None = None
        self._own_input_until = 0.0

    def pause(self, reason: str = "Operations are paused on the device; the computer can't be operated for now.") -> None:
        self.paused = reason

    def resume(self) -> None:
        self.paused = None

    def emergency_stop(self) -> None:
        self.paused = "The device owner triggered an emergency stop"
        if self._current is not None and not self._current.done():
            self._current.cancel()

        self._notify({"event": "stopped"})

    def sent_input_recently(self) -> bool:
        # An Esc sent by the framework itself doesn't count as an emergency stop
        return time.monotonic() <= self._own_input_until

    def _notify(self, event: dict[str, Any]) -> None:
        if self.on_activity is not None:
            with contextlib.suppress(Exception):
                self.on_activity(event)

    async def handle(self, op: str, arguments: dict[str, Any]) -> Any:
        if op == "screenshot":
            # Scale and crop on the executor: full-size images of large screens can be several MB, while the model only needs about 1280x800
            self._check_paused()
            png = await self.backend.screenshot()

            # Live view (watch) requests carry the previous frame's hash: when the screen hasn't changed, nothing is compressed or sent
            digest = hashlib.sha1(png).hexdigest()
            if arguments.get("unless_hash") == digest:
                return {"unchanged": True, "hash": digest}

            max_size = arguments.get("max_size")
            region = arguments.get("region")
            result = await asyncio.to_thread(
                capture, png, tuple(max_size) if max_size else None, tuple(region) if region else None
            )
            result["hash"] = digest
            return result

        if op == "size":
            return list(await self.backend.size())
        if op == "frontmost":
            return await self.apps.frontmost()
        if op == "apps":
            apps = await self.apps.running()
            if arguments.get("installed"):
                apps = apps + await self.apps.installed()
            return [public(app) for app in apps]
        if op == "open_app":
            return await self.open_app(
                str(arguments["app"]),
                policy=(
                    ComputerPolicy.model_validate(arguments["policy"])
                    if arguments.get("policy")
                    else ComputerPolicy.open()
                ),
                grants=arguments.get("grants") or {},
                session=arguments.get("session"),
            )
        if op == "act":
            return await self.act(
                arguments["action"],
                arguments.get("args") or {},
                policy=(
                    ComputerPolicy.model_validate(arguments["policy"])
                    if arguments.get("policy")
                    else ComputerPolicy.open()
                ),
                grants=arguments.get("grants") or {},
                session=arguments.get("session"),
            )
        if op == "user_act":
            return await self.user_act(arguments["action"], arguments.get("args") or {})
        raise ValueError(f"Unsupported screen operation: {op}")

    def _check_paused(self) -> None:
        if self.paused:
            raise PermissionError(self.paused)

    async def act(
        self,
        action: str,
        args: dict[str, Any],
        *,
        policy: ComputerPolicy,
        grants: dict[str, Any],
        session: str | None = None,
    ) -> Any:
        if action not in ACTIONS or action in ("screenshot", "zoom"):
            raise ValueError(f"Unsupported action: {action}")

        async with self._lock:
            self._check_paused()

            if is_input(action):
                frontmost = await self.apps.frontmost()
                targets = await self._target_apps(action, args, frontmost)
                for target in targets:
                    problem = check(
                        policy,
                        action,
                        args,
                        frontmost=frontmost,
                        target=target,
                        grants=grants,
                    )
                    if problem is None and self.ceiling is not None:
                        problem = ceiling_check(self.ceiling, action, args, target)
                    if problem is not None:
                        raise PermissionError(problem)

                app = targets[0]
                self._notify(
                    {
                        "event": "action",
                        "session": session,
                        "action": action,
                        "app": safe_app_name((app or {}).get("name")),
                    }
                )

            self._current = asyncio.current_task()
            try:
                return await self._perform(action, args)
            except asyncio.CancelledError:
                if self.paused:
                    raise PermissionError(self.paused) from None
                raise
            finally:
                self._current = None
                if action in KEYBOARD:
                    self._own_input_until = time.monotonic() + OWN_INPUT_WINDOW

    async def user_act(self, action: str, args: dict[str, Any]) -> Any:
        if action not in ACTIONS or action in ("screenshot", "zoom"):
            raise ValueError(f"Unsupported action: {action}")

        async with self._lock:
            self._check_paused()

            if is_input(action) and self.ceiling is not None:
                for target in await self._target_apps(action, args, await self.apps.frontmost()):
                    problem = ceiling_check(self.ceiling, action, args, target)
                    if problem is not None:
                        raise PermissionError(problem)

            self._notify({"event": "user_action", "action": action})

            try:
                return await self._perform(action, args)
            finally:
                if action in KEYBOARD:
                    self._own_input_until = time.monotonic() + OWN_INPUT_WINDOW

    async def _target_apps(self, action: str, args: dict[str, Any], frontmost: Any) -> list[Any]:
        if action in KEYBOARD:
            return [frontmost]

        points = (
            [args.get("start_coordinate"), args.get("coordinate")]
            if action == "left_click_drag"
            else [args.get("coordinate")]
        )
        targets = []
        for point in points:
            at = point if point is not None else await self.backend.cursor_position()
            targets.append(await self.apps.app_at(int(at[0]), int(at[1])))

        return targets

    async def open_app(
        self, query: str, *, policy: ComputerPolicy, grants: dict[str, Any], session: str | None = None
    ) -> dict[str, Any]:
        async with self._lock:
            self._check_paused()
            app = find_app(query, await self.apps.running(), await self.apps.installed())
            if app is None:
                raise LookupError(f"App not found: {safe_app_name(query)}")

            problem = check_open(policy, app, grants)
            if problem is None and self.ceiling is not None:
                problem = ceiling_check_open(self.ceiling, app)
            if problem is not None:
                raise PermissionError(problem)

            self._notify(
                {
                    "event": "action",
                    "session": session,
                    "action": "open_app",
                    "app": safe_app_name(app.get("name")),
                }
            )
            await self.apps.open(app)
            frontmost = await self.apps.frontmost()
            deadline = time.monotonic() + OPEN_TIMEOUT
            while not same_app(frontmost, app) and time.monotonic() < deadline:
                await asyncio.sleep(0.3)
                frontmost = await self.apps.frontmost()

            if not same_app(frontmost, app):
                current = safe_app_name((frontmost or {}).get("name")) if frontmost else "none"
                raise RuntimeError(
                    f"Requested to open {safe_app_name(app.get('name'))}, but it couldn't be brought to the front (current foreground: {current})"
                )
            return public(app)

    async def _perform(self, action: str, args: dict[str, Any]) -> Any:
        backend = self.backend
        point = args.get("coordinate")

        if action in KEYBOARD:
            # An Esc received while sending keys comes from the framework itself
            self._own_input_until = float("inf")

        if action.endswith("_click") and action != "left_click_drag":
            if point is None:
                point = await backend.cursor_position()

            button = {"right_click": "right", "middle_click": "middle"}.get(action, "left")
            count = {"double_click": 2, "triple_click": 3}.get(action, 1)
            await backend.click(int(point[0]), int(point[1]), button, count, str(args.get("text") or ""))
        elif action == "left_click_drag":
            start, end = args["start_coordinate"], args["coordinate"]
            await backend.drag((int(start[0]), int(start[1])), (int(end[0]), int(end[1])), str(args.get("text") or ""))
        elif action == "mouse_move":
            if point is None:
                raise ValueError("mouse_move requires the coordinate argument")
            await backend.move(int(point[0]), int(point[1]))
        elif action == "left_mouse_down":
            await backend.mouse_down("left")
        elif action == "left_mouse_up":
            await backend.mouse_up("left")
        elif action == "cursor_position":
            x, y = await backend.cursor_position()
            return {"x": x, "y": y}
        elif action == "scroll":
            if point is None:
                point = await backend.cursor_position()

            direction = args["scroll_direction"]
            if direction not in ("up", "down", "left", "right"):
                raise ValueError(f"Invalid scroll_direction value {direction!r}; valid values are up, down, left, right")

            amount = max(1, min(int(args.get("scroll_amount") or 3), 50))
            await backend.scroll(int(point[0]), int(point[1]), direction, amount, str(args.get("text") or ""))
        elif action == "type":
            await backend.type(str(args.get("text") or ""))
        elif action == "key":
            await backend.key(str(args["text"]), max(1, min(int(args.get("repeat") or 1), 100)))
        elif action == "hold_key":
            await backend.hold_key(str(args["text"]), min(float(args.get("duration") or 1), 300))
        elif action == "wait":
            await asyncio.sleep(min(float(args.get("duration") or 1), 300))

        return None


def start_escape_listener(on_escape: Callable[[], None]) -> Any:
    loop = asyncio.get_running_loop()

    try:
        from pynput import keyboard
    except ImportError:
        logger.warning("pynput is not installed, so the global Esc emergency stop can't be registered; run pip install pynput")
        return None

    def on_press(key: Any, injected: bool = False) -> None:
        if injected:
            # Keys the system marks as injected by a program (Windows), not pressed by the user
            return
        if key == keyboard.Key.esc:
            loop.call_soon_threadsafe(on_escape)

    listener = keyboard.Listener(on_press=on_press)
    listener.daemon = True
    listener.start()
    return listener
