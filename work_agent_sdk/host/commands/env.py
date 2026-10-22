from __future__ import annotations

import os
import re

# 命令默认只获得执行节点上的以下环境变量；后端进程中的其他变量（如数据库地址、各类密钥）一律不传递
INHERITED_NAMES = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LANGUAGE",
        "TERM",
        "TZ",
        "DISPLAY",
        "XAUTHORITY",
        "WAYLAND_DISPLAY",
        "XDG_RUNTIME_DIR",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "TEMP",
        "TMP",
    }
)


def is_inherited(name: str, extra: tuple[str, ...] | list[str] = ()) -> bool:
    return name in INHERITED_NAMES or name.startswith("LC_") or name in extra


ENV_VAR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def check_command_env(env: dict[str, str]) -> None:
    for name in env:
        if not ENV_VAR_NAME.fullmatch(name):
            raise PermissionError(f"环境变量名不合法：{name!r}")


def inherited_variables(extra: list[str] | tuple[str, ...] = ()) -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if is_inherited(name, extra)}
