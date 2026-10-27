from __future__ import annotations

import json
import os
import shlex
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from work_agent_sdk.host.files.paths import DEFAULT_DENY_READ, PathStyle


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SRT(_Config):
    """
    Anthropic sandbox-runtime (srt), which must be installed on the node the workspace is on. Relative paths in protect are relative to the workspace;
    network lists the domains that may be accessed.
    """

    kind: Literal["srt"] = "srt"
    write: list[str] = Field(default_factory=list)
    read: list[str] = Field(default_factory=list)
    deny_read: list[str] = Field(default_factory=lambda: list(DEFAULT_DENY_READ))
    protect: list[str] = Field(default_factory=list)
    network: list[str] = Field(default_factory=list)
    binary: str = "srt"
    nested: bool = False
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("network", mode="before")
    @classmethod
    def _network(cls, value: Any) -> Any:
        if value is True:
            raise ValueError("srt doesn't support fully open network access; list the domains to allow")
        return [] if value is False or value is None else value


class NoSandbox(_Config):
    """No sandbox: commands and file operations run directly on the node."""

    kind: Literal["none"] = "none"

    # Provides the same path attributes as SRT, all set to unrestricted
    @property
    def write(self) -> list[str]:
        return []

    @property
    def read(self) -> list[str]:
        return []

    @property
    def deny_read(self) -> list[str]:
        return []

    @property
    def protect(self) -> list[str]:
        return []


Sandbox = Annotated[SRT | NoSandbox, Field(discriminator="kind")]


class NodeSandbox(BaseModel):
    kind: Literal["none", "srt"] = "none"
    # Domain upper bound set by the device owner; None means no bound
    network: list[str] | None = None
    allow_unsandboxed: bool = False


def effective_kind(backend: Sandbox, node: NodeSandbox | None) -> str:
    if node is not None and node.kind != "none":
        return node.kind
    return backend.kind


def effective_network(backend: Sandbox, node: NodeSandbox | None) -> list[str]:
    """Domains srt actually allows: those listed by the backend, further limited by the node's bound. No network access when the backend lists none (NoSandbox)."""
    allowed = list(backend.network) if isinstance(backend, SRT) else []
    if node is None or node.network is None:
        return allowed
    return [domain for domain in allowed if domain in node.network]


def inside_roots(paths: list[str], roots: list[str], resolve: Callable[[str], str], style: PathStyle) -> list[str]:
    return [path for path in paths if any(style.inside(resolve(path), root) for root in roots)]


def unsandboxed_allowed(node: NodeSandbox | None) -> bool:
    return node is None or node.kind == "none" or node.allow_unsandboxed


@dataclass
class Scope:
    workspace: str
    cwd: str
    tmp: str
    data_dir: str
    home: str
    shell: str = "bash"
    os: str = "linux"
    readable: list[str] = field(default_factory=list)

    @property
    def writable(self) -> list[str]:
        return [self.workspace, self.tmp]

    @property
    def style(self) -> PathStyle:
        return PathStyle(self.os)

    def absolute(self, path: str, base: str | None = None) -> str:
        return self.style.absolute(path, self.home, base or self.workspace)


def resolved_rules(sandbox: Sandbox, scope: Scope) -> dict[str, list[str]]:
    return {
        "write": [scope.absolute(path) for path in sandbox.write],
        "read": [scope.absolute(path) for path in sandbox.read],
        "deny_read": [scope.absolute(path, scope.home) for path in sandbox.deny_read],
        "protect": [scope.absolute(path) for path in sandbox.protect],
    }


def srt_config(sandbox: SRT, scope: Scope) -> dict[str, Any]:
    rules = resolved_rules(sandbox, scope)

    # Paths given to srt are all resolved to real paths on the executor: srt doesn't recognize allowed read/write directories given as symlinks,
    # and when given a link the directory can be accessed neither via the link nor via the real path; denied paths are resolved too, rather than relying on srt's own handling
    def real(paths: list[str]) -> list[str]:
        return [os.path.realpath(path) for path in paths]

    config: dict[str, Any] = {
        "filesystem": {
            "denyRead": real(rules["deny_read"]),
            "allowRead": real([*scope.writable, *scope.readable, *rules["read"]]),
            "allowWrite": real([*scope.writable, *rules["write"]]),
            "denyWrite": real(rules["protect"]),
        },
        "network": {
            "allowedDomains": list(sandbox.network),
            "deniedDomains": [],
            "strictAllowlist": True,
        },
    }
    if sandbox.nested:
        config["enableWeakerNestedSandbox"] = True

    return deep_merge(config, sandbox.settings)


async def wrap(sandbox: Sandbox, command: str, scope: Scope) -> list[str]:
    inner = f"export TMPDIR={shlex.quote(scope.tmp)}; {command}"
    if isinstance(sandbox, NoSandbox):
        return [scope.shell, "-c", inner]
    if scope.os == "windows":
        raise NotImplementedError(
            "srt requires a POSIX shell, so no sandbox is available on Windows; deploy the device daemon as a workspace on a Linux machine, container or virtual machine"
        )

    config = json.dumps(srt_config(sandbox, scope), ensure_ascii=False, sort_keys=True)

    # Look up srt in the executing node's own PATH, so the command's environment variables can't swap the program used
    binary = shutil.which(sandbox.binary) or sandbox.binary
    script = (
        f"{shlex.quote(binary)} --settings /dev/fd/3 -c {shlex.quote(inner)} "
        f"3<<'WORK_AGENT_SRT_SETTINGS'\n{config}\nWORK_AGENT_SRT_SETTINGS"
    )
    return ["sh", "-c", script]


def deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


__all__ = ["SRT", "NoSandbox", "Sandbox", "Scope", "DEFAULT_DENY_READ", "wrap"]
