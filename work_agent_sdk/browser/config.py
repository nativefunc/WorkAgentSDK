from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from work_agent_sdk.browser.actions import BROWSER

PROFILE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DEFAULT_VIEWPORT = (1280, 800)
# 默认关闭的浏览器动作；启用后在 standard 策略下每次执行需用户确认
OPTIONAL_BROWSER_ACTIONS = tuple(action.name for action in BROWSER if action.optional)


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrowserPolicy(_Config):
    """浏览器安全策略。standard() 只允许公网 http(s)，可选动作每次需确认，不向敏感输入框输入；open() 不做限制。"""

    allow: bool | list[str] = True
    deny: list[str] = Field(default_factory=list)
    private: bool | list[str] = False
    enable: list[str] = Field(default_factory=list)
    confirm: list[str] = Field(default_factory=list)
    sensitive_inputs: bool = False

    @field_validator("enable")
    @classmethod
    def _enable(cls, value: list[str]) -> list[str]:
        unknown = set(value) - set(OPTIONAL_BROWSER_ACTIONS)
        if unknown:
            raise ValueError(f"enable 包含未知动作 {sorted(unknown)}；可选值为 {list(OPTIONAL_BROWSER_ACTIONS)}")
        return value

    @classmethod
    def standard(
        cls,
        *,
        allow: bool | list[str] = True,
        deny: list[str] | None = None,
        private: bool | list[str] = False,
        enable: list[str] | tuple[str, ...] = (),
    ) -> BrowserPolicy:
        return cls(
            allow=allow,
            deny=list(deny or []),
            private=private,
            enable=list(enable),
            confirm=list(enable),
            sensitive_inputs=False,
        )

    @classmethod
    def open(cls) -> BrowserPolicy:
        return cls(allow=True, private=True, enable=list(OPTIONAL_BROWSER_ACTIONS), sensitive_inputs=True)

    def enabled(self, action: str) -> bool:
        return action not in OPTIONAL_BROWSER_ACTIONS or action in self.enable


class Browser(_Config):
    """
    会话树共用的浏览器，各会话使用各自的标签页。download_dir 省略时为框架在浏览器所在节点上的目录，
    顶层会话关闭时删除。
    """

    node: str | None = None
    cdp: str | None = None
    profile: str = "session"
    policy: BrowserPolicy = Field(default_factory=BrowserPolicy.standard)
    headless: bool | None = None
    args: list[str] = Field(default_factory=list)
    executable: str | None = None
    viewport: tuple[int, int] = DEFAULT_VIEWPORT
    downloads: bool = True
    download_dir: str | None = None
    description: str = ""

    @model_validator(mode="after")
    def _check(self) -> Browser:
        if not self.node and not self.cdp:
            raise ValueError("Browser 缺少 node 和 cdp；请至少指定其中之一")
        if self.profile == "shared" and not self.cdp:
            raise ValueError('profile="shared" 仅适用于通过 cdp 连接的浏览器；请同时指定 cdp')
        if self.profile not in ("session", "shared") and not PROFILE_NAME.match(self.profile):
            raise ValueError(
                f"profile 的取值 {self.profile!r} 无效；可选 session、shared，或仅含字母、数字、-、_ 的名称"
            )
        if self.download_dir is not None and not self.can_manage_downloads:
            raise ValueError('download_dir 需要框架管理下载；请指定 node（浏览器所在节点），且 profile 不为 "shared"')
        if "file_upload" in self.policy.enable and not self.node:
            raise ValueError("启用 file_upload 需要指定 node（浏览器所在节点）：上传时将该节点上的文件路径交给浏览器")
        return self

    @property
    def can_manage_downloads(self) -> bool:
        return bool(self.node) and self.profile != "shared"

    def to_config(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
