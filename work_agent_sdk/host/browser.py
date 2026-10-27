from __future__ import annotations

import asyncio
import contextlib
import glob
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel

from work_agent_sdk.host.commands.env import inherited_variables
from work_agent_sdk.host.commands.process import spawn_detached, stop_process_group
from work_agent_sdk.host.files.paths import NodePaths, local_style
from work_agent_sdk.host.websocket import WebSocket

logger = logging.getLogger("work_agent_sdk")

PROFILE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
EXECUTABLE_NAMES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome", "msedge")
EXECUTABLE_PATTERNS = {
    "linux": (
        "/opt/pw-browsers/chromium",
        "/opt/pw-browsers/chromium-*/chrome-linux64/chrome",
        "/opt/pw-browsers/chromium-*/chrome-linux-arm64/chrome",
        "~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome",
        "~/.cache/ms-playwright/chromium-*/chrome-linux-arm64/chrome",
    ),
    "darwin": (
        "~/Library/Caches/ms-playwright/chromium-*/chrome-mac-*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ),
    "win32": (
        "%PROGRAMFILES%\\Google\\Chrome\\Application\\chrome.exe",
        "%PROGRAMFILES(X86)%\\Google\\Chrome\\Application\\chrome.exe",
        "%LOCALAPPDATA%\\Google\\Chrome\\Application\\chrome.exe",
        "%PROGRAMFILES(X86)%\\Microsoft\\Edge\\Application\\msedge.exe",
        "%PROGRAMFILES%\\Microsoft\\Edge\\Application\\msedge.exe",
        "%LOCALAPPDATA%\\ms-playwright\\chromium-*\\chrome-win64\\chrome.exe",
    ),
}
# The backend may only use the following launch arguments on a device; any others (such as replacing the renderer process command) amount to running arbitrary programs on the device
SAFE_ARG_PREFIXES = (
    "--proxy-server=",
    "--proxy-bypass-list=",
    "--lang=",
    "--window-size=",
    "--window-position=",
    "--force-device-scale-factor=",
    "--user-agent=",
)
SAFE_ARGS = ("--start-maximized", "--disable-gpu", "--mute-audio")
PORT_FILE = "DevToolsActivePort"
LAUNCH_FILE = "work-agent-launch.json"
START_TIMEOUT = 15
STOP_TIMEOUT = 5
PROBE_TIMEOUT = 2

# Browsers launched during this run (profile → process handle): only these may be force-killed, and they are reaped so they don't become zombies after exiting
_launched: dict[str, subprocess.Popen] = {}
_locks: dict[str, asyncio.Lock] = {}


class BrowserOptions(BaseModel):
    profile: str
    headless: bool
    display: str | None = None
    args: tuple[str, ...] = ()
    executable: str | None = None


def profile_dir(profile: str) -> str:
    if not PROFILE_NAME.match(profile):
        raise ValueError(f"Invalid profile name: {profile!r}; only letters, digits, - and _ are allowed")
    return NodePaths(os.path.expanduser("~"), local_style()).browser_profile(profile)


def check_safe_args(args: tuple[str, ...] | list[str]) -> None:
    for arg in args:
        if arg not in SAFE_ARGS and not arg.startswith(SAFE_ARG_PREFIXES):
            raise PermissionError(f"The device doesn't allow this browser launch argument: {arg}")


def _tail(path: str, lines: int = 20) -> str:
    try:
        with open(path, errors="replace") as file:
            return "".join(file.readlines()[-lines:]).strip()
    except OSError:
        return ""


def find_executable() -> str | None:
    for name in EXECUTABLE_NAMES:
        path = shutil.which(name)
        if path:
            return path

    platform = sys.platform if sys.platform in ("win32", "darwin") else "linux"
    for pattern in EXECUTABLE_PATTERNS[platform]:
        for path in sorted(glob.glob(os.path.expandvars(os.path.expanduser(pattern))), reverse=True):
            if os.access(path, os.X_OK) and os.path.isfile(path):
                return path

    return None


def _port_file(directory: str) -> tuple[int, str] | None:
    try:
        with open(os.path.join(directory, PORT_FILE)) as file:
            lines = file.read().splitlines()
    except OSError:
        return None

    if len(lines) < 2 or not lines[0].strip().isdigit() or not lines[1].startswith("/devtools/browser/"):
        return None
    return int(lines[0].strip()), lines[1].strip()


async def _browser_identity(port: int) -> str | None:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), PROBE_TIMEOUT)
    except (TimeoutError, OSError):
        return None

    try:
        # Chromium's debugging server only accepts HTTP/1.1 and keeps the connection open after replying, so read the body by Content-Length
        writer.write(b"GET /json/version HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), PROBE_TIMEOUT)
        lines = head.decode("latin-1").split("\r\n")
        if not lines[0].startswith("HTTP/1.1 200"):
            return None

        length = next((int(line.split(":", 1)[1]) for line in lines if line.lower().startswith("content-length:")), 0)
        if not 0 < length <= 65536:
            return None

        body = await asyncio.wait_for(reader.readexactly(length), PROBE_TIMEOUT)
        url = json.loads(body.decode(errors="replace")).get("webSocketDebuggerUrl", "")
        return urlsplit(url).path or None
    except (TimeoutError, OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError, AttributeError):
        return None
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def running_port(profile: str) -> int | None:
    recorded = _port_file(profile_dir(profile))
    if recorded is None:
        return None

    port, identity = recorded
    return port if await _browser_identity(port) == identity else None


async def framework_ports() -> set[int]:
    root = NodePaths(os.path.expanduser("~"), local_style()).browser_root
    ports = set()
    for path in glob.glob(os.path.join(root, "*", PORT_FILE)):
        name = os.path.basename(os.path.dirname(path))
        port = await running_port(name) if PROFILE_NAME.match(name) else None
        if port is not None:
            ports.add(port)

    return ports


def _own_process(profile: str) -> subprocess.Popen | None:
    process = _launched.get(profile)
    if process is not None and process.poll() is not None:
        _launched.pop(profile, None)
        return None
    return process


def launch_settings(options: BrowserOptions) -> dict[str, Any]:
    executable = options.executable or find_executable()
    if executable is None:
        raise RuntimeError("Chromium not found; install Chromium, Chrome or Edge, or specify the executable with executable")

    display = None if options.headless else options.display or os.environ.get("DISPLAY") or None
    return {
        "executable": executable,
        "headless": options.headless,
        "args": list(options.args),
        "display": display,
    }


def _recorded_settings(profile: str) -> dict[str, Any] | None:
    try:
        with open(os.path.join(profile_dir(profile), LAUNCH_FILE)) as file:
            recorded = json.load(file)
    except (OSError, ValueError):
        return None
    return recorded if isinstance(recorded, dict) else None


def _describe(settings: dict[str, Any] | None) -> str:
    if settings is None:
        return "unknown settings"

    parts = ["headless" if settings.get("headless") else "headed"]
    if settings.get("display"):
        parts.append(f"display {settings['display']}")

    parts.append(f"launch arguments {' '.join(settings.get('args') or []) or 'none'}")
    parts.append(f"program {settings.get('executable')}")
    return ", ".join(parts)


async def start_browser(options: BrowserOptions) -> int:
    async with _locks.setdefault(options.profile, asyncio.Lock()):
        settings = launch_settings(options)
        port = await running_port(options.profile)
        if port is not None:
            recorded = _recorded_settings(options.profile)
            if recorded != settings:
                raise RuntimeError(
                    f"Browser profile {options.profile} is already running ({_describe(recorded)}), which doesn't match the requested settings"
                    f" ({_describe(settings)}); use a different profile for different settings, or close that browser first"
                )
            return port

        own = _own_process(options.profile)
        if own is not None:
            # The process started in this run is still running but the debugging port doesn't respond: treat it as hung, kill it and restart
            logger.warning("Browser profile %s is not responding; restarting it", options.profile)
            await _force_stop(options.profile, own)

        return await _launch(options, settings)


async def _launch(options: BrowserOptions, settings: dict[str, Any]) -> int:
    executable = settings["executable"]
    directory = profile_dir(options.profile)

    # Don't delete the old DevToolsActivePort: the browser rewrites it on startup and the old identifier won't match; deleting it would make it impossible to recognize a browser still holding the profile
    os.makedirs(directory, exist_ok=True)

    # Write the settings before launching: launches of the same profile are serialized by a lock and only happen when no browser is running, so the record matches the browser launched next
    with open(os.path.join(directory, LAUNCH_FILE), "w") as file:
        json.dump(settings, file)

    flags = [
        f"--user-data-dir={directory}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=0",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,MediaRouter",
        "--password-store=basic",
        # Disable the back-forward cache (bfcache): pages restored from it don't fire DOMContentLoaded again, so back/forward and later actions wait until timeout.
        # Playwright adds this argument too when it launches Chromium itself
        "--disable-back-forward-cache",
    ]
    if options.headless:
        flags.append("--headless=new")
    if sys.platform != "win32" and os.geteuid() == 0:
        flags.append("--no-sandbox")

    flags += list(options.args)
    variables = inherited_variables()
    if settings["display"]:
        variables["DISPLAY"] = settings["display"]

    log_path = os.path.join(directory, "work-agent.log")
    with open(log_path, "wb") as log:
        process = spawn_detached([executable, *flags], env=variables, output=log)

    _launched[options.profile] = process
    loop = asyncio.get_running_loop()
    deadline = loop.time() + START_TIMEOUT
    while loop.time() < deadline:
        recorded = _port_file(directory)
        if recorded is not None and await _browser_identity(recorded[0]) == recorded[1]:
            return recorded[0]
        if process.poll() is not None:
            break

        await asyncio.sleep(0.1)

    await _force_stop(options.profile, process)
    detail = _tail(log_path)
    raise RuntimeError(
        f"Failed to launch Chromium: {detail or 'no output'} (if the profile is held by an unresponsive browser, end that browser first)"
    )


async def stop_browser(profile: str) -> None:
    async with _locks.setdefault(profile, asyncio.Lock()):
        port = await running_port(profile)
        if port is not None:
            await _close_over_cdp(port)

        own = _own_process(profile)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + STOP_TIMEOUT
        while loop.time() < deadline:
            if await running_port(profile) is None and (own is None or own.poll() is not None):
                break
            await asyncio.sleep(0.1)
        else:
            if own is not None and own.poll() is None:
                await _force_stop(profile, own)
            elif await running_port(profile) is not None:
                # Launched by a previous run and this process holds no handle: don't kill by PID (it may now belong to another program); leave it to be handled manually
                logger.warning("Browser profile %s didn't respond to Browser.close and was not force-killed", profile)
                return

        _launched.pop(profile, None)

        for name in (PORT_FILE, LAUNCH_FILE):
            with contextlib.suppress(FileNotFoundError):
                os.remove(os.path.join(profile_dir(profile), name))


async def _close_over_cdp(port: int) -> None:
    identity = await _browser_identity(port)
    if identity is None:
        return

    try:
        socket = await WebSocket.connect(f"ws://127.0.0.1:{port}{identity}", timeout=PROBE_TIMEOUT)
    except Exception:
        return

    try:
        await socket.send_text(json.dumps({"id": 1, "method": "Browser.close"}))
        with contextlib.suppress(Exception):
            await asyncio.wait_for(socket.receive_text(), PROBE_TIMEOUT)
    except Exception:
        pass
    finally:
        with contextlib.suppress(Exception):
            await socket.close()


async def _force_stop(profile: str, process: subprocess.Popen) -> None:
    if process.poll() is None:
        stop_process_group(process)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + STOP_TIMEOUT + 2
        while process.poll() is None and loop.time() < deadline:
            await asyncio.sleep(0.1)
    _launched.pop(profile, None)
