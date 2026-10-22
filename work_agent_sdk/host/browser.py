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
        "/opt/pw-browsers/chromium-*/chrome-linux/chrome",
        "~/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
    ),
    "darwin": (
        "~/Library/Caches/ms-playwright/chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ),
    "win32": (
        "%PROGRAMFILES%\\Google\\Chrome\\Application\\chrome.exe",
        "%PROGRAMFILES(X86)%\\Google\\Chrome\\Application\\chrome.exe",
        "%LOCALAPPDATA%\\Google\\Chrome\\Application\\chrome.exe",
        "%PROGRAMFILES(X86)%\\Microsoft\\Edge\\Application\\msedge.exe",
        "%PROGRAMFILES%\\Microsoft\\Edge\\Application\\msedge.exe",
        "%LOCALAPPDATA%\\ms-playwright\\chromium-*\\chrome-win\\chrome.exe",
    ),
}
# 后端在设备上只能使用以下启动参数；其他参数（如替换渲染进程的命令）等同于在设备上执行任意程序
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

# 本次运行中启动的浏览器（profile → 进程句柄）：仅对其执行强制结束，并负责回收，以免退出后成为僵尸进程
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
        raise ValueError(f"profile 名称不合法：{profile!r}；仅允许字母、数字、- 和 _")
    return NodePaths(os.path.expanduser("~"), local_style()).browser_profile(profile)


def check_safe_args(args: tuple[str, ...] | list[str]) -> None:
    for arg in args:
        if arg not in SAFE_ARGS and not arg.startswith(SAFE_ARG_PREFIXES):
            raise PermissionError(f"设备不允许该浏览器启动参数：{arg}")


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
        # Chromium 的调试服务只接受 HTTP/1.1，且答复后不断开连接，因此按 Content-Length 读取正文
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
        raise RuntimeError("未找到 Chromium；请安装 Chromium、Chrome 或 Edge，或通过 executable 指定可执行文件")

    display = None if options.headless else options.display or os.environ.get("DISPLAY") or None
    return {"executable": executable, "headless": options.headless, "args": list(options.args), "display": display}


def _recorded_settings(profile: str) -> dict[str, Any] | None:
    try:
        with open(os.path.join(profile_dir(profile), LAUNCH_FILE)) as file:
            recorded = json.load(file)
    except (OSError, ValueError):
        return None
    return recorded if isinstance(recorded, dict) else None


def _describe(settings: dict[str, Any] | None) -> str:
    if settings is None:
        return "设置未知"

    parts = ["无界面" if settings.get("headless") else "有界面"]
    if settings.get("display"):
        parts.append(f"桌面 {settings['display']}")

    parts.append(f"启动参数 {' '.join(settings.get('args') or []) or '无'}")
    parts.append(f"程序 {settings.get('executable')}")
    return "，".join(parts)


async def start_browser(options: BrowserOptions) -> int:
    async with _locks.setdefault(options.profile, asyncio.Lock()):
        settings = launch_settings(options)
        port = await running_port(options.profile)
        if port is not None:
            recorded = _recorded_settings(options.profile)
            if recorded != settings:
                raise RuntimeError(
                    f"浏览器 profile {options.profile} 已在运行（{_describe(recorded)}），与本次要求的设置"
                    f"（{_describe(settings)}）不一致；请为不同的设置使用不同的 profile，或先关闭该浏览器"
                )
            return port

        own = _own_process(options.profile)
        if own is not None:
            # 本次启动的进程仍在运行但调试端口无响应：视为卡死，结束后重新启动
            logger.warning("浏览器 profile %s 无响应，将重新启动", options.profile)
            await _force_stop(options.profile, own)

        return await _launch(options, settings)


async def _launch(options: BrowserOptions, settings: dict[str, Any]) -> int:
    executable = settings["executable"]
    directory = profile_dir(options.profile)

    # 不删除旧的 DevToolsActivePort：浏览器启动后会重写它，旧标识对不上；删掉反而认不出仍占用该 profile 的浏览器
    os.makedirs(directory, exist_ok=True)

    # 先写入设置再启动：同一 profile 的启动由锁串行，且只在没有浏览器运行时进行，记录与随后启动的浏览器一致
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
        # 关闭后退缓存（bfcache）：从缓存恢复的页面不会再触发 DOMContentLoaded，后退/前进及之后的操作会一直等到超时。
        # Playwright 自己启动 Chromium 时同样加这个参数
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
        f"启动 Chromium 失败：{detail or '无输出'}（若该 profile 正被一个无响应的浏览器占用，请先结束该浏览器）"
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
                # 由上次运行启动、本进程未持有句柄：不按进程号结束（该进程号可能已属于其他程序），交由人工处理
                logger.warning("浏览器 profile %s 未响应 Browser.close，且未被强制结束", profile)
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
