from __future__ import annotations

import asyncio
import configparser
import contextlib
import glob
import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any

from work_agent_sdk.host.screen.backends import XDisplay, default_display

# 打开应用后等待其窗口切到前台的最长秒数（包括启动时间）
OPEN_TIMEOUT = 20
# 已安装应用的列表在执行端缓存的秒数
INSTALLED_CACHE_SECONDS = 60


class AppsBackend:
    async def frontmost(self) -> dict[str, Any] | None:
        return None

    async def app_at(self, x: int, y: int) -> dict[str, Any] | None:
        return None

    async def running(self) -> list[dict[str, Any]]:
        return []

    async def installed(self) -> list[dict[str, Any]]:
        return []

    async def open(self, app: dict[str, Any]) -> None:
        raise NotImplementedError("该屏幕不支持打开应用")


def same_app(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    if not a or not b:
        return False
    if a.get("id") and b.get("id") and str(a["id"]).lower() == str(b["id"]).lower():
        return True

    exe_a, exe_b = str(a.get("exe") or ""), str(b.get("exe") or "")
    return bool(exe_a) and exe_a.lower() == exe_b.lower()


def find_app(query: str, *candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    needle = query.strip().lower()
    if not needle:
        return None

    apps = [app for group in candidates for app in group]
    for test in (
        lambda app: str(app.get("id") or "").lower() == needle,
        lambda app: str(app.get("name") or "").lower() == needle,
        lambda app: needle in str(app.get("name") or "").lower(),
        lambda app: needle in str(app.get("id") or "").lower(),
    ):
        found = next((app for app in apps if test(app)), None)
        if found is not None:
            return found

    return None


def public(app: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in app.items() if key != "launch"}


# .desktop 文件 Exec 中的占位符（打开应用时不传文件），见 freedesktop Desktop Entry 规范
EXEC_FIELD_CODES = re.compile(r"%[fFuUdDnNickvm]")


class XApps(XDisplay, AppsBackend):
    def __init__(self, display: str) -> None:
        super().__init__(display)
        self._installed: tuple[float, list[dict[str, Any]]] | None = None

    async def _window_app(self, window: str) -> dict[str, Any] | None:
        if not window or window in ("0", "0x0"):
            return None

        app: dict[str, Any] = {}
        with contextlib.suppress(RuntimeError):
            text = await self._run("xprop", "-id", window, "WM_CLASS")
            names = [part.strip().strip('"') for part in text.split("=", 1)[-1].split(",")]
            if "=" in text and names and names[-1]:
                app["id"] = names[-1]
                app["name"] = names[-1]

        with contextlib.suppress(RuntimeError, ValueError, OSError):
            pid = int((await self._xdotool("getwindowpid", window)).strip())
            app["pid"] = pid
            app["exe"] = os.path.realpath(f"/proc/{pid}/exe")

        if not app.get("id") and app.get("exe"):
            app["id"] = app["exe"]
            app["name"] = os.path.basename(app["exe"])

        return app or None

    async def frontmost(self) -> dict[str, Any] | None:
        try:
            window = (await self._xdotool("getactivewindow")).strip()
        except RuntimeError:
            return None
        return await self._window_app(window)

    async def _windows_top_down(self) -> list[str]:
        with contextlib.suppress(RuntimeError):
            text = await self._run("xprop", "-root", "_NET_CLIENT_LIST_STACKING")
            if "#" in text:
                # EWMH 规定该列表自下而上排列
                return list(reversed(re.findall(r"0x[0-9a-fA-F]+", text.split("#", 1)[1])))

        # 没有窗口管理器时，根窗口的子窗口即应用窗口，xwininfo 按自上而下列出
        text = await self._run("xwininfo", "-root", "-children")
        return re.findall(r"^\s+(0x[0-9a-fA-F]+) ", text.split("children:", 1)[-1], re.MULTILINE)

    async def _geometry(self, window: str) -> tuple[int, int, int, int] | None:
        try:
            text = await self._run("xwininfo", "-id", window)
        except RuntimeError:
            return None

        if "IsViewable" not in text:
            return None

        values = {}
        for name in ("Absolute upper-left X", "Absolute upper-left Y", "Width", "Height"):
            match = re.search(re.escape(name) + r":\s+(-?\d+)", text)
            if match is None:
                return None
            values[name] = int(match.group(1))

        return (
            values["Absolute upper-left X"],
            values["Absolute upper-left Y"],
            values["Width"],
            values["Height"],
        )

    async def app_at(self, x: int, y: int) -> dict[str, Any] | None:
        for window in await self._windows_top_down():
            box = await self._geometry(window)
            if box and box[0] <= x < box[0] + box[2] and box[1] <= y < box[1] + box[3]:
                return await self._window_app(window)
        return None

    async def running(self) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for window in await self._windows_top_down():
            if await self._geometry(window) is None:
                continue
            app = await self._window_app(window)
            if app and app.get("id"):
                found.setdefault(str(app["id"]).lower(), app)
        return list(found.values())

    async def installed(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._installed is None or now - self._installed[0] > INSTALLED_CACHE_SECONDS:
            self._installed = (now, await asyncio.to_thread(desktop_entries))
        return self._installed[1]

    async def _windows_of(self, app: dict[str, Any]) -> list[str]:
        result = []
        for window in await self._windows_top_down():
            if await self._geometry(window) is None:
                continue
            if same_app(await self._window_app(window), app):
                result.append(window)

        return result

    async def open(self, app: dict[str, Any]) -> None:
        windows = await self._windows_of(app)
        if not windows:
            command = (app.get("launch") or {}).get("exec")
            if not command:
                raise RuntimeError(f"{app.get('name')} 未在运行，且无法确定其启动方式")

            argv = shlex.split(EXEC_FIELD_CODES.sub("", command).replace("%%", "%"))
            if not argv or shutil.which(argv[0]) is None:
                raise RuntimeError(f"无法启动 {app.get('name')}：找不到程序 {argv[0] if argv else command}")

            subprocess.Popen(  # noqa: S603  启动的是该应用 .desktop 文件中声明的程序
                argv,
                env=self._env(),
                cwd=os.path.expanduser("~"),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            deadline = time.monotonic() + OPEN_TIMEOUT
            while not windows and time.monotonic() < deadline:
                await asyncio.sleep(0.3)
                windows = await self._windows_of(app)

            if not windows:
                raise RuntimeError(f"已启动 {app.get('name')}，但 {OPEN_TIMEOUT} 秒内未出现窗口")

        with contextlib.suppress(RuntimeError):
            # 需要窗口管理器支持 _NET_ACTIVE_WINDOW；不支持时由调用方核对前台并报错
            await self._xdotool("windowactivate", "--sync", windows[0], timeout=10)


def desktop_dirs() -> list[str]:
    home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    data = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    extra = [os.path.expanduser("~/.local/share/flatpak/exports/share"), "/var/lib/flatpak/exports/share"]
    dirs = []
    for base in [home, *data, *extra]:
        path = os.path.join(base, "applications")
        if base and path not in dirs and os.path.isdir(path):
            dirs.append(path)

    return dirs


def desktop_entries(dirs: list[str] | None = None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    apps = []
    for directory in dirs if dirs is not None else desktop_dirs():
        for path in sorted(glob.glob(os.path.join(directory, "**", "*.desktop"), recursive=True)):
            desktop_id = os.path.relpath(path, directory).replace(os.sep, "-")
            if desktop_id in seen:
                continue

            seen.add(desktop_id)
            entry = _read_desktop_entry(path)
            if entry is None:
                continue

            program = shlex.split(EXEC_FIELD_CODES.sub("", entry["Exec"]))[:1]
            identity = entry.get("StartupWMClass") or desktop_id.removesuffix(".desktop")
            apps.append(
                {
                    "id": identity,
                    "name": entry.get("Name") or identity,
                    "exe": (shutil.which(program[0]) or program[0]) if program else "",
                    "launch": {"desktop": path, "exec": entry["Exec"]},
                }
            )

    return apps


def _read_desktop_entry(path: str) -> dict[str, str] | None:
    parser = configparser.RawConfigParser(strict=False, interpolation=None)

    # 键区分大小写
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError):
        return None

    if not parser.has_section("Desktop Entry"):
        return None

    entry = dict(parser.items("Desktop Entry"))
    if entry.get("Type") != "Application" or not entry.get("Exec"):
        return None
    if entry.get("NoDisplay", "").lower() == "true" or entry.get("Hidden", "").lower() == "true":
        return None
    return entry


MAC_APP_DIRS = (
    "/Applications",
    "/Applications/Utilities",
    "/System/Applications",
    "/System/Applications/Utilities",
    "~/Applications",
)


class MacApps(AppsBackend):
    def __init__(self) -> None:
        self._installed: tuple[float, list[dict[str, Any]]] | None = None

    async def frontmost(self) -> dict[str, Any] | None:
        return await asyncio.to_thread(_mac_frontmost)

    async def app_at(self, x: int, y: int) -> dict[str, Any] | None:
        return await asyncio.to_thread(_mac_app_at, int(x), int(y))

    async def running(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(_mac_running)

    async def installed(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._installed is None or now - self._installed[0] > INSTALLED_CACHE_SECONDS:
            self._installed = (now, await asyncio.to_thread(mac_bundles))
        return self._installed[1]

    async def open(self, app: dict[str, Any]) -> None:
        bundle = (app.get("launch") or {}).get("bundle")
        argv = ["/usr/bin/open", "-b", str(app["id"])] if app.get("id") else ["/usr/bin/open", str(bundle)]
        process = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await asyncio.wait_for(process.communicate(), OPEN_TIMEOUT)
        if process.returncode != 0:
            raise RuntimeError(f"无法打开 {app.get('name')}：{stderr.decode(errors='replace').strip()}")


def _mac_app(app: Any) -> dict[str, Any]:
    return {
        "id": str(app.bundleIdentifier() or ""),
        "name": str(app.localizedName() or ""),
        "exe": str(app.executableURL().path() if app.executableURL() else ""),
        "pid": int(app.processIdentifier()),
    }


def _mac_frontmost() -> dict[str, Any] | None:
    try:
        from AppKit import NSWorkspace
    except ImportError:
        return None
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return _mac_app(app) if app is not None else None


def _mac_running() -> list[dict[str, Any]]:
    try:
        from AppKit import NSApplicationActivationPolicyRegular, NSWorkspace
    except ImportError:
        return []

    # 只列出普通应用（有程序坞图标的），不含后台进程和菜单栏工具
    return [
        _mac_app(app)
        for app in NSWorkspace.sharedWorkspace().runningApplications()
        if app.activationPolicy() == NSApplicationActivationPolicyRegular
    ]


def _mac_app_at(x: int, y: int) -> dict[str, Any] | None:
    try:
        import Quartz
        from AppKit import NSRunningApplication
    except ImportError:
        return None

    options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    for window in Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []:
        if window.get("kCGWindowLayer", 0) != 0:
            continue

        bounds = window.get("kCGWindowBounds") or {}
        left, top = bounds.get("X", 0), bounds.get("Y", 0)
        if left <= x < left + bounds.get("Width", 0) and top <= y < top + bounds.get("Height", 0):
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(int(window.get("kCGWindowOwnerPID", 0)))
            return _mac_app(app) if app is not None else None

    return None


def mac_bundles(dirs: tuple[str, ...] = MAC_APP_DIRS) -> list[dict[str, Any]]:
    apps: dict[str, dict[str, Any]] = {}
    for directory in dirs:
        for bundle in sorted(glob.glob(os.path.join(os.path.expanduser(directory), "*.app"))):
            try:
                with open(os.path.join(bundle, "Contents", "Info.plist"), "rb") as file:
                    info = plistlib.load(file)
            except (OSError, plistlib.InvalidFileException, ValueError):
                continue

            identity = str(info.get("CFBundleIdentifier") or "")
            if not identity or identity.lower() in apps:
                continue

            name = info.get("CFBundleDisplayName") or info.get("CFBundleName") or os.path.basename(bundle)[:-4]
            executable = info.get("CFBundleExecutable")
            apps[identity.lower()] = {
                "id": identity,
                "name": str(name),
                "exe": os.path.join(bundle, "Contents", "MacOS", executable) if executable else "",
                "launch": {"bundle": bundle},
            }

    return list(apps.values())


# 列出开始菜单中指向 .exe 的快捷方式；身份为目标程序路径的小写形式，与正在运行的应用一致
WINDOWS_START_MENU_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$dirs = @([Environment]::GetFolderPath('CommonStartMenu'), [Environment]::GetFolderPath('StartMenu'))
$shell = New-Object -ComObject WScript.Shell
$apps = Get-ChildItem -Path $dirs -Recurse -Filter *.lnk | ForEach-Object {
  $target = $shell.CreateShortcut($_.FullName).TargetPath
  if ($target -and $target.ToLower().EndsWith('.exe')) {
    [pscustomobject]@{ name = $_.BaseName; target = $target; link = $_.FullName }
  }
}
@($apps) | ConvertTo-Json -Compress
"""


class WindowsApps(AppsBackend):
    def __init__(self) -> None:
        self._installed: tuple[float, list[dict[str, Any]]] | None = None

    async def frontmost(self) -> dict[str, Any] | None:
        return await asyncio.to_thread(_windows_frontmost)

    async def app_at(self, x: int, y: int) -> dict[str, Any] | None:
        return await asyncio.to_thread(_windows_app_at, int(x), int(y))

    async def running(self) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for _, app in await asyncio.to_thread(_windows_top_level):
            found.setdefault(app["id"], app)
        return list(found.values())

    async def installed(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._installed is None or now - self._installed[0] > INSTALLED_CACHE_SECONDS:
            self._installed = (now, await _windows_start_menu())
        return self._installed[1]

    async def open(self, app: dict[str, Any]) -> None:
        windows = [window for window, other in await asyncio.to_thread(_windows_top_level) if same_app(other, app)]
        if windows:
            await asyncio.to_thread(_windows_bring_to_front, windows[0])
            return

        target = (app.get("launch") or {}).get("link") or app.get("exe")
        if not target:
            raise RuntimeError(f"{app.get('name')} 未在运行，且无法确定其启动方式")

        # os.startfile 仅 Windows 提供
        await asyncio.to_thread(os.startfile, target)  # type: ignore[attr-defined]
        deadline = time.monotonic() + OPEN_TIMEOUT
        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            windows = [window for window, other in await asyncio.to_thread(_windows_top_level) if same_app(other, app)]
            if windows:
                await asyncio.to_thread(_windows_bring_to_front, windows[0])
                return

        raise RuntimeError(f"已启动 {app.get('name')}，但 {OPEN_TIMEOUT} 秒内未出现窗口")


async def _windows_start_menu() -> list[dict[str, Any]]:
    process = await asyncio.create_subprocess_exec(
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_START_MENU_SCRIPT,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    stdout, _ = await asyncio.wait_for(process.communicate(), 60)
    text = stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return []

    data = json.loads(text)
    items = data if isinstance(data, list) else [data]
    apps: dict[str, dict[str, Any]] = {}
    for item in items:
        target = str(item.get("target") or "")
        if not target or "unins" in os.path.basename(target).lower():
            continue
        apps.setdefault(
            target.lower(),
            {"id": target.lower(), "name": str(item.get("name") or os.path.basename(target)), "exe": target,
             "launch": {"link": item.get("link")}},
        )  # fmt: skip

    return list(apps.values())


def _windows_app(window: int) -> dict[str, Any] | None:
    import ctypes
    from ctypes import wintypes

    if not window:
        return None

    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(window, ctypes.byref(pid))  # type: ignore[attr-defined]
    process_query_limited_information = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid.value)  # type: ignore[attr-defined]
    if not handle:
        return None

    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):  # type: ignore[attr-defined]
            return None

        path = buffer.value
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]

    return {"id": path.lower(), "name": os.path.basename(path), "exe": path, "pid": pid.value}


def _windows_frontmost() -> dict[str, Any] | None:
    import ctypes

    return _windows_app(ctypes.windll.user32.GetForegroundWindow())  # type: ignore[attr-defined]


def _windows_app_at(x: int, y: int) -> dict[str, Any] | None:
    import ctypes
    from ctypes import wintypes

    window = ctypes.windll.user32.WindowFromPoint(wintypes.POINT(x, y))  # type: ignore[attr-defined]
    ga_root = 2
    root = ctypes.windll.user32.GetAncestor(window, ga_root)  # type: ignore[attr-defined]
    return _windows_app(root or window)


def _windows_top_level() -> list[tuple[int, dict[str, Any]]]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    gwl_exstyle, ws_ex_toolwindow, gw_owner = -20, 0x00000080, 4
    found: list[tuple[int, dict[str, Any]]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)  # type: ignore[attr-defined]
    def visit(window: int, _: int) -> bool:
        if not user32.IsWindowVisible(window) or user32.GetWindowTextLengthW(window) == 0:
            return True
        if user32.GetWindow(window, gw_owner) or user32.GetWindowLongW(window, gwl_exstyle) & ws_ex_toolwindow:
            return True

        app = _windows_app(window)
        if app is not None:
            found.append((window, app))

        return True

    user32.EnumWindows(visit, 0)
    return found


def _windows_bring_to_front(window: int) -> None:
    # 系统只允许前台进程设置前台窗口，所以临时附加到当前前台线程的输入队列
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    sw_restore = 9
    if user32.IsIconic(window):
        user32.ShowWindow(window, sw_restore)
    if user32.SetForegroundWindow(window):
        return

    current = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    own = kernel32.GetCurrentThreadId()
    attached = current and current != own and user32.AttachThreadInput(own, current, True)
    try:
        user32.BringWindowToTop(window)
        user32.SetForegroundWindow(window)
    finally:
        if attached:
            user32.AttachThreadInput(own, current, False)


def local_apps(display: str | None) -> AppsBackend:
    display = display or default_display()
    if display:
        return XApps(display)
    if sys.platform == "darwin":
        return MacApps()
    if sys.platform == "win32":
        return WindowsApps()
    return AppsBackend()
