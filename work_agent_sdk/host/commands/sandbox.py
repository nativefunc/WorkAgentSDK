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
    Anthropic sandbox-runtime（srt），需安装在工作区所在的节点上。protect 中的相对路径以工作区为基准，
    network 为允许访问的域名。
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
            raise ValueError("srt 不支持完全开放网络；请列出允许访问的域名")
        return [] if value is False or value is None else value


class NoSandbox(_Config):
    """不使用沙箱：命令和文件操作直接在节点上执行。"""

    kind: Literal["none"] = "none"

    # 与 SRT 提供相同的属性，取值均为不限制
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

    @property
    def network(self) -> bool:
        return True


Sandbox = Annotated[SRT | NoSandbox, Field(discriminator="kind")]


class NodeSandbox(BaseModel):
    kind: Literal["none", "srt"] = "none"
    network: bool | list[str] = True
    allow_unsandboxed: bool = False


def intersect_network(backend: bool | list[str], node: bool | list[str]) -> bool | list[str]:
    if backend is False or node is False:
        return False
    if backend is True:
        return node
    if node is True:
        return backend
    return [domain for domain in backend if domain in node]


def effective_kind(backend: Sandbox, node: NodeSandbox | None) -> str:
    if node is not None and node.kind != "none":
        return node.kind
    return backend.kind


def effective_network(backend: Sandbox, node: NodeSandbox | None) -> bool | list[str]:
    return backend.network if node is None else intersect_network(backend.network, node.network)


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

    # 交给 srt 的路径一律解析为执行端的真实路径：srt 不认符号链接形式的允许读写目录，
    # 给出链接时该目录既不能经链接、也不能经真实路径访问；禁止读写的路径一并解析，不依赖 srt 自身的处理
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
            "srt 需要 POSIX shell，Windows 上不提供沙箱；请在 Linux 机器、容器或虚拟机中部署设备守护进程作为工作区"
        )

    config = json.dumps(srt_config(sandbox, scope), ensure_ascii=False, sort_keys=True)

    # 按执行节点自身的 PATH 查找 srt，避免命令的环境变量替换所用程序
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
