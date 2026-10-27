from __future__ import annotations

import asyncio
import contextlib
import io
import os
import struct
import sys
from collections.abc import Iterable
from typing import Any

from work_agent_sdk.host.commands.env import inherited_variables
from work_agent_sdk.host.commands.process import collect_output, run_process
from work_agent_sdk.host.screen.actions import key_parts

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SCROLL_BUTTONS = {"up": 4, "down": 5, "left": 6, "right": 7}
XDOTOOL_BUTTONS = {"left": 1, "middle": 2, "right": 3}
XDOTOOL_KEYS = {
    "enter": "Return",
    "return": "Return",
    "esc": "Escape",
    "escape": "Escape",
    "backspace": "BackSpace",
    "tab": "Tab",
    "space": "space",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "arrowup": "Up",
    "arrowdown": "Down",
    "arrowleft": "Left",
    "arrowright": "Right",
    "delete": "Delete",
    "home": "Home",
    "end": "End",
    "pageup": "Page_Up",
    "pagedown": "Page_Down",
    "pgup": "Page_Up",
    "pgdn": "Page_Down",
    "cmd": "super",
    "command": "super",
    "win": "super",
    "meta": "super",
    "control": "ctrl",
    "option": "alt",
}


def png_size(data: bytes) -> tuple[int, int]:
    if not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise ValueError("Screenshot data is not in PNG format")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


class ScreenBackend:
    async def screenshot(self) -> bytes:
        raise NotImplementedError

    async def size(self) -> tuple[int, int]:
        return png_size(await self.screenshot())

    async def click(self, x: int, y: int, button: str = "left", count: int = 1, modifiers: str = "") -> None:
        raise NotImplementedError

    async def mouse_down(self, button: str = "left") -> None:
        raise NotImplementedError

    async def mouse_up(self, button: str = "left") -> None:
        raise NotImplementedError

    async def move(self, x: int, y: int) -> None:
        raise NotImplementedError

    async def drag(self, start: tuple[int, int], end: tuple[int, int], modifiers: str = "") -> None:
        await self.move(*start)
        await self.mouse_down()
        await self.move(*end)
        await self.mouse_up()

    async def scroll(self, x: int, y: int, direction: str, amount: int, modifiers: str = "") -> None:
        raise NotImplementedError

    async def type(self, text: str) -> None:
        raise NotImplementedError

    async def key(self, combination: str, repeat: int = 1) -> None:
        raise NotImplementedError

    async def hold_key(self, combination: str, duration: float) -> None:
        raise NotImplementedError

    async def cursor_position(self) -> tuple[int, int]:
        raise NotImplementedError


class XDisplay:
    def __init__(self, display: str) -> None:
        self.display = display

    def _env(self) -> dict[str, str]:
        return {**inherited_variables(), "DISPLAY": self.display}

    def _exec(self, argv: list[str], timeout: float) -> Any:
        return run_process(argv, env=self._env(), timeout=timeout)

    async def _run(self, *argv: str, timeout: float = 30) -> str:
        try:
            result = await collect_output(self._exec(list(argv), timeout))
        except FileNotFoundError:
            raise RuntimeError(f"{argv[0]} is not installed on this machine") from None
        if result.exit_code != 0:
            raise RuntimeError(f"Desktop command failed: {' '.join(argv[:2])}: {result.stderr.strip()}")
        return result.stdout

    async def _xdotool(self, *arguments: str | int, timeout: float = 30) -> str:
        return await self._run("xdotool", *[str(item) for item in arguments], timeout=timeout)


class XScreen(XDisplay, ScreenBackend):
    async def screenshot(self) -> bytes:
        try:
            from PIL import ImageGrab
        except ImportError:
            raise RuntimeError("Screenshots require Pillow; run pip install Pillow") from None

        def grab() -> bytes:
            buffer = io.BytesIO()
            ImageGrab.grab(xdisplay=self.display).save(buffer, format="PNG")
            return buffer.getvalue()

        return await asyncio.to_thread(grab)

    async def size(self) -> tuple[int, int]:
        with contextlib.suppress(RuntimeError, ValueError):
            width, height = (await self._xdotool("getdisplaygeometry")).split()
            return int(width), int(height)
        return await super().size()

    async def _with_modifiers(self, modifiers: str, arguments: list[str | int]) -> None:
        keys = [_x_key(part) for part in key_parts(modifiers)] if modifiers else []
        await self._xdotool(*_key_events("keydown", keys), *arguments, *_key_events("keyup", reversed(keys)))

    async def click(self, x: int, y: int, button: str = "left", count: int = 1, modifiers: str = "") -> None:
        arguments: list[str | int] = [
            "mousemove",
            int(x),
            int(y),
            "click",
            "--repeat",
            int(count),
            _button(button),
        ]
        await self._with_modifiers(modifiers, arguments)

    async def mouse_down(self, button: str = "left") -> None:
        await self._xdotool("mousedown", _button(button))

    async def mouse_up(self, button: str = "left") -> None:
        await self._xdotool("mouseup", _button(button))

    async def move(self, x: int, y: int) -> None:
        await self._xdotool("mousemove", int(x), int(y))

    async def drag(self, start: tuple[int, int], end: tuple[int, int], modifiers: str = "") -> None:
        arguments: list[str | int] = [
            "mousemove", int(start[0]), int(start[1]), "mousedown", 1,
            "mousemove", int(end[0]), int(end[1]), "mouseup", 1,
        ]  # fmt: skip
        await self._with_modifiers(modifiers, arguments)

    async def scroll(self, x: int, y: int, direction: str, amount: int, modifiers: str = "") -> None:
        arguments: list[str | int] = ["mousemove", int(x), int(y), "click", "--repeat", max(1, int(amount))]
        arguments.append(SCROLL_BUTTONS[direction])
        await self._with_modifiers(modifiers, arguments)

    async def type(self, text: str) -> None:
        await self._xdotool("type", "--delay", 12, "--", text, timeout=120)

    async def key(self, combination: str, repeat: int = 1) -> None:
        combination = "+".join(_x_key(part) for part in key_parts(combination))
        await self._xdotool("key", "--repeat", max(1, int(repeat)), "--", combination)

    async def hold_key(self, combination: str, duration: float) -> None:
        keys = [_x_key(part) for part in key_parts(combination)]
        await self._xdotool(*_key_events("keydown", keys))
        try:
            await asyncio.sleep(min(float(duration), 300))
        finally:
            await self._xdotool(*_key_events("keyup", reversed(keys)))

    async def cursor_position(self) -> tuple[int, int]:
        values = await self._mouse_location()
        return int(values.get("X", 0)), int(values.get("Y", 0))

    async def _mouse_location(self) -> dict[str, str]:
        values = {}
        for item in (await self._xdotool("getmouselocation", "--shell")).split():
            if "=" in item:
                name, value = item.split("=", 1)
                values[name] = value
        return values


class DesktopScreen(ScreenBackend):
    def __init__(self) -> None:
        try:
            import pyautogui
        except ImportError:
            raise RuntimeError("Screen control requires pyautogui; run pip install Pillow pyautogui") from None
        pyautogui.FAILSAFE = False
        self._gui = pyautogui

    async def _call(self, name: str, *arguments: Any, **options: Any) -> Any:
        return await asyncio.to_thread(getattr(self._gui, name), *arguments, **options)

    async def screenshot(self) -> bytes:
        image = await self._call("screenshot")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    async def size(self) -> tuple[int, int]:
        width, height = await self._call("size")
        return int(width), int(height)

    async def _holding(self, modifiers: str, action: Any) -> None:
        keys = [_gui_key(part) for part in key_parts(modifiers)] if modifiers else []
        for key in keys:
            await self._call("keyDown", key)
        try:
            await action()
        finally:
            for key in reversed(keys):
                await self._call("keyUp", key)

    async def click(self, x: int, y: int, button: str = "left", count: int = 1, modifiers: str = "") -> None:
        await self._holding(
            modifiers,
            lambda: self._call(
                "click",
                x=x,
                y=y,
                button=button,
                clicks=count,
            ),
        )

    async def mouse_down(self, button: str = "left") -> None:
        await self._call("mouseDown", button=button)

    async def mouse_up(self, button: str = "left") -> None:
        await self._call("mouseUp", button=button)

    async def move(self, x: int, y: int) -> None:
        await self._call("moveTo", x, y)

    async def scroll(self, x: int, y: int, direction: str, amount: int, modifiers: str = "") -> None:
        async def wheel() -> None:
            await self._call("moveTo", x, y)
            if direction in ("up", "down"):
                await self._call("scroll", (amount if direction == "up" else -amount) * 100)
            else:
                await self._call("hscroll", (amount if direction == "right" else -amount) * 100)

        await self._holding(modifiers, wheel)

    async def type(self, text: str) -> None:
        await self._call("write", text, interval=0.01)

    async def key(self, combination: str, repeat: int = 1) -> None:
        keys = [_gui_key(part) for part in key_parts(combination)]
        for _ in range(max(1, int(repeat))):
            await self._call("hotkey", *keys)

    async def hold_key(self, combination: str, duration: float) -> None:
        keys = [_gui_key(part) for part in key_parts(combination)]
        await self._holding("+".join(keys), lambda: asyncio.sleep(min(float(duration), 300)))

    async def cursor_position(self) -> tuple[int, int]:
        x, y = await self._call("position")
        return int(x), int(y)


def _button(button: str) -> int:
    if button not in XDOTOOL_BUTTONS:
        raise ValueError(f"Unsupported mouse button: {button}")
    return XDOTOOL_BUTTONS[button]


def _x_key(name: str) -> str:
    return XDOTOOL_KEYS.get(name.lower(), name)


def _key_events(action: str, keys: Iterable[str]) -> list[str]:
    events: list[str] = []
    for key in keys:
        events += [action, key]
    return events


def _gui_key(name: str) -> str:
    lowered = name.lower()
    return {
        "super": "command" if sys.platform == "darwin" else "win",
        "return": "enter",
        "control": "ctrl",
    }.get(lowered, lowered)


def default_display() -> str | None:
    if sys.platform.startswith("linux"):
        return os.environ.get("DISPLAY") or ":0"
    return None


def local_screen(display: str | None) -> ScreenBackend:
    display = display or default_display()
    if display:
        return XScreen(display)
    return DesktopScreen()
