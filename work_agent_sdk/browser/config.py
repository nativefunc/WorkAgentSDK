from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from work_agent_sdk.browser.actions import BROWSER

PROFILE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DEFAULT_VIEWPORT = (1280, 800)
# Browser actions that are off by default; once enabled, each run under the standard policy needs user confirmation
OPTIONAL_BROWSER_ACTIONS = tuple(action.name for action in BROWSER if action.optional)


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrowserPolicy(_Config):

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
            raise ValueError(f"enable contains unknown actions {sorted(unknown)}; valid values are {list(OPTIONAL_BROWSER_ACTIONS)}")
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
        return cls(
            allow=True,
            private=True,
            enable=list(OPTIONAL_BROWSER_ACTIONS),
            sensitive_inputs=True,
        )

    def enabled(self, action: str) -> bool:
        return action not in OPTIONAL_BROWSER_ACTIONS or action in self.enable


class Browser(_Config):
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
            raise ValueError("Browser is missing both node and cdp; specify at least one of them")
        if self.profile == "shared" and not self.cdp:
            raise ValueError('profile="shared" only applies to browsers connected via cdp; also specify cdp')
        if self.profile not in ("session", "shared") and not PROFILE_NAME.match(self.profile):
            raise ValueError(
                f"Invalid profile value {self.profile!r}; valid values are session, shared, or a name containing only letters, digits, - and _"
            )
        if self.download_dir is not None and not self.can_manage_downloads:
            raise ValueError('download_dir requires the framework to manage downloads; specify node (the node the browser runs on), and profile must not be "shared"')
        if "file_upload" in self.policy.enable and not self.node:
            raise ValueError("Enabling file_upload requires node (the node the browser runs on): uploads hand file paths on that node to the browser")
        return self

    @property
    def can_manage_downloads(self) -> bool:
        return bool(self.node) and self.profile != "shared"

    def to_config(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
