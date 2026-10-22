from __future__ import annotations

import fnmatch
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from work_agent_sdk.host.screen.actions import (
    KEYBOARD,
    POINTER,
    is_input,
    is_system_key,
)


class Tier(StrEnum):
    """应用的可操作级别。"""

    VIEW = "view"
    CLICK = "click"
    FULL = "full"


class Hold(StrEnum):
    """屏幕占用时长：每轮结束时释放，或由整个会话树占用至顶层会话结束。"""

    TURN = "turn"
    SESSION = "session"


class ComputerMode(StrEnum):
    OPEN = "open"
    STANDARD = "standard"


class SystemKeys(StrEnum):
    ASK = "ask"
    ALLOW = "allow"
    DENY = "deny"


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


DEFAULT_TIERS: dict[Tier, list[str]] = {
    # 浏览器和交易软件仅可查看（网页操作应使用浏览器工具，其具备网址规则）
    Tier.VIEW: [
        "com.google.Chrome*",
        "com.apple.Safari*",
        "org.mozilla.firefox*",
        "com.microsoft.edgemac*",
        "com.brave.Browser*",
        "company.thebrowser.Browser",
        "chrome.exe",
        "msedge.exe",
        "firefox.exe",
        "brave.exe",
        "google-chrome*",
        "chromium*",
        "firefox*",
        "microsoft-edge*",
        "*futu*",
        "*tradingview*",
        "*tonghuashun*",
        "*eastmoney*",
        "*thinkorswim*",
    ],
    # 终端和 IDE 仅可点击（禁止输入，以免绕过工作区的沙箱）
    Tier.CLICK: [
        "com.apple.Terminal",
        "com.googlecode.iterm2",
        "dev.warp.Warp*",
        "net.kovidgoyal.kitty",
        "io.alacritty",
        "WindowsTerminal.exe",
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "gnome-terminal*",
        "konsole",
        "xterm",
        "*terminal*",
        "com.microsoft.VSCode*",
        "com.todesktop.*",
        "com.jetbrains.*",
        "com.apple.dt.Xcode",
        "Code.exe",
        "Cursor.exe",
        "idea64.exe",
        "pycharm64.exe",
        "code",
        "cursor",
        "jetbrains-*",
    ],
}
DEFAULT_COMPUTER_DENY = ["com.apple.keychainaccess", "*1password*", "*bitwarden*", "*keepass*"]


class ComputerPolicy(_Config):
    """电脑操作规则，随每个动作发送给执行端检查。"""

    mode: ComputerMode = ComputerMode.STANDARD
    allow: dict[str, Tier | None] = Field(default_factory=dict)
    deny: list[str] = Field(default_factory=list)
    tiers: dict[Tier, list[str]] = Field(default_factory=lambda: {k: list(v) for k, v in DEFAULT_TIERS.items()})
    system_keys: SystemKeys = SystemKeys.ASK
    hold: Hold = Hold.SESSION

    @field_validator("allow", mode="before")
    @classmethod
    def _allow(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return dict.fromkeys(value)
        if isinstance(value, dict):
            return {pattern: (tier or None) for pattern, tier in value.items()}
        return value or {}

    @classmethod
    def open(cls, *, hold: Hold | str = Hold.TURN) -> ComputerPolicy:
        return cls(mode=ComputerMode.OPEN, tiers={}, system_keys=SystemKeys.ALLOW, hold=hold)

    @classmethod
    def standard(
        cls,
        allow: list[str] | dict[str, Any] | None = None,
        *,
        deny: list[str] | None = None,
        tiers: dict[str, list[str]] | None = None,
        system_keys: SystemKeys | str = SystemKeys.ASK,
        hold: Hold | str = Hold.SESSION,
    ) -> ComputerPolicy:
        fields: dict[str, Any] = {
            "mode": ComputerMode.STANDARD,
            "allow": allow or {},
            "deny": DEFAULT_COMPUTER_DENY + list(deny or []),
            "system_keys": system_keys,
            "hold": hold,
        }
        if tiers is not None:
            fields["tiers"] = tiers

        return cls(**fields)


class DeviceCeiling(_Config):
    """设备所有者为屏幕设定的上限，后端规则只能在此范围内生效。deny 始终禁止操作；max_tier 为允许的最高级别。"""

    deny: list[str] = Field(default_factory=list)
    max_tier: Tier = Tier.FULL

    def __init__(self, deny: list[str] | None = None, max_tier: Tier | str | None = None, /, **data: Any) -> None:
        if deny is not None:
            data["deny"] = deny
        if max_tier is not None:
            data["max_tier"] = max_tier
        super().__init__(**data)


TIERS = tuple(Tier)
APP_NAME = re.compile(r"[^\w .()+&'-]", re.UNICODE)


def safe_app_name(name: Any) -> str:
    # 防止借应用名伪造指令
    text = APP_NAME.sub("", str(name or "")).strip()
    return text[:40] or "（未知应用）"


def app_keys(app: dict[str, Any] | None) -> list[str]:
    if not app:
        return []

    keys = [str(app.get("id") or ""), str(app.get("name") or "")]
    exe = str(app.get("exe") or "")
    if exe:
        keys += [exe, exe.replace("\\", "/").rsplit("/", 1)[-1]]

    return [key.lower() for key in keys if key]


def matches(app: dict[str, Any] | None, patterns: Any) -> bool:
    keys = app_keys(app)
    return any(fnmatch.fnmatchcase(key, str(pattern).lower()) for key in keys for pattern in patterns)


def app_id(app: dict[str, Any] | None) -> str:
    if not app:
        return ""
    return str(app.get("id") or app.get("exe") or app.get("name") or "")


def identity_keys(app: dict[str, Any] | None) -> list[str]:
    # 不按名称匹配：名称可由应用自行设定
    if not app:
        return []
    return [str(value).lower() for value in (app.get("id"), app.get("exe")) if value]


def tier_of(policy: ComputerPolicy, app: dict[str, Any] | None, grants: dict[str, Any] | None = None) -> Tier | None:
    if policy.mode == ComputerMode.OPEN:
        return Tier.FULL
    if matches(app, policy.deny):
        return None

    granted_apps = {str(key).lower(): tier for key, tier in ((grants or {}).get("apps") or {}).items()}
    granted = next((granted_apps[key] for key in identity_keys(app) if key in granted_apps), None)
    listed = next((tier or "" for pattern, tier in policy.allow.items() if matches(app, [pattern])), None)
    if granted is None and listed is None:
        return None

    explicit = granted or listed
    if explicit:
        return Tier(explicit)
    return default_tier(policy, app)


def default_tier(policy: ComputerPolicy, app: dict[str, Any] | None) -> Tier:
    for tier in TIERS:
        if matches(app, policy.tiers.get(tier, [])):
            return tier
    return Tier.FULL


def check(
    policy: ComputerPolicy,
    action: str,
    args: dict[str, Any],
    *,
    frontmost: dict[str, Any] | None,
    target: dict[str, Any] | None,
    grants: dict[str, Any] | None = None,
) -> str | None:
    if policy.mode == ComputerMode.OPEN or not is_input(action):
        return None

    app = frontmost if action in KEYBOARD else target
    if app is None:
        return "无法确定该动作作用的应用，已拒绝"

    name = safe_app_name(app.get("name") or app.get("id"))
    if matches(app, policy.deny):
        return f"不允许操作 {name}"

    tier = tier_of(policy, app, grants)
    if tier is None:
        return f"尚未获得操作 {name} 的授权；请先通过 computer_request_access 申请"
    if tier == Tier.VIEW:
        return f"{name} 仅允许查看，不允许点击或输入"

    modifiers = str(args.get("text") or "") if action not in KEYBOARD else ""
    if tier == Tier.CLICK and (action not in POINTER or modifiers):
        return f"{name} 仅允许点击和滚动，不允许输入、按键或拖动"

    if action in ("key", "hold_key") and is_system_key(str(args.get("text") or "")):
        allowed = policy.system_keys == SystemKeys.ALLOW or (
            policy.system_keys == SystemKeys.ASK and (grants or {}).get("system_keys")
        )
        if not allowed:
            return "系统组合键需要用户授权；请在调用 computer_request_access 时设置 system_keys=true"

    return None


def check_open(policy: ComputerPolicy, app: dict[str, Any], grants: dict[str, Any] | None = None) -> str | None:
    if policy.mode == ComputerMode.OPEN:
        return None

    name = safe_app_name(app.get("name") or app.get("id"))
    if matches(app, policy.deny):
        return f"不允许操作 {name}"
    if tier_of(policy, app, grants) is None:
        return f"尚未获得操作 {name} 的授权；请先通过 computer_request_access 申请"
    return None


def ceiling_check_open(ceiling: DeviceCeiling, app: dict[str, Any]) -> str | None:
    if ceiling.deny and matches(app, ceiling.deny):
        return f"设备所有者不允许操作 {safe_app_name(app.get('name'))}"
    if ceiling.max_tier == Tier.VIEW:
        return "设备所有者仅允许查看屏幕"
    return None


def ceiling_check(ceiling: DeviceCeiling, action: str, args: dict[str, Any], app: dict[str, Any] | None) -> str | None:
    if not is_input(action):
        return None
    if ceiling.deny and matches(app, ceiling.deny):
        return f"设备所有者不允许操作 {safe_app_name((app or {}).get('name'))}"
    if ceiling.max_tier == Tier.VIEW:
        return "设备所有者仅允许查看屏幕"
    if ceiling.max_tier == Tier.CLICK and (action not in POINTER or args.get("text")):
        return "设备所有者仅允许点击和滚动"
    return None


__all__ = [
    "ComputerPolicy",
    "DeviceCeiling",
    "safe_app_name",
    "matches",
    "app_id",
    "identity_keys",
    "tier_of",
    "default_tier",
    "check",
    "ceiling_check",
    "check_open",
    "ceiling_check_open",
]
