from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any

import work_agent_sdk.host.files.helper as helper
from work_agent_sdk.device.protect import is_protected
from work_agent_sdk.host.commands.sandbox import (
    SRT,
    NodeSandbox,
    NoSandbox,
    Sandbox,
    Scope,
    effective_kind,
    effective_network,
    inside_roots,
    unsandboxed_allowed,
)
from work_agent_sdk.host.files.paths import (
    DEFAULT_DENY_READ,
    NodePaths,
    PathRules,
    PathStyle,
    local_style,
)


def _union(*lists: list[str]) -> list[str]:
    merged: list[str] = []
    for items in lists:
        merged.extend(item for item in items if item not in merged)
    return merged


def real_path(path: str) -> str:
    return os.path.realpath(os.path.normpath(os.path.expanduser(path)))


@dataclass
class DevicePolicy:
    # 开放的目录（真实路径）
    roots: list[str]
    sandbox: str = "none"
    network: bool | list[str] = True
    # 是否允许后端审批过的命令在沙箱外执行（仅在设备配置了沙箱时有意义）
    allow_unsandboxed: bool = False
    # 保护模板：standard 或 none（见 protect.py）
    protect: str = "standard"
    # 以下几项决定沙箱外运行什么程序、沙箱有多牢固，只由设备所有者决定
    srt_binary: str = "srt"
    srt_nested: bool = False
    srt_settings: dict[str, Any] = field(default_factory=dict)
    home: str = field(default_factory=lambda: os.path.expanduser("~"))
    # 设备守护进程运行在本机，路径按本机系统处理
    style: PathStyle = field(default_factory=local_style)

    @property
    def node_sandbox(self) -> NodeSandbox:
        return NodeSandbox(kind=self.sandbox, network=self.network, allow_unsandboxed=self.allow_unsandboxed)

    def _inside(self, path: str, root: str) -> bool:
        return self.style.inside(path, root)

    @property
    def paths(self) -> NodePaths:
        return NodePaths(real_path(self.home), self.style)

    @property
    def data_dir(self) -> str:
        return real_path(self.paths.data_dir)

    @property
    def framework_dirs(self) -> list[str]:
        # 在已解析符号链接的数据目录下拼接名称（不再解析这些目录本身，以免其被替换为链接时将其他位置变为框架目录）
        return [os.path.join(self.data_dir, os.path.basename(path)) for path in self.paths.framework_dirs]

    @property
    def standard(self) -> bool:
        return self.protect == "standard"

    def is_protected(self, path: str) -> bool:
        return self.standard and is_protected(self.style, path)

    @property
    def rules(self) -> PathRules:
        # standard 模板禁止写入钩子和 shell 配置：写进去的脚本会在设备所有者下次操作时于沙箱外执行
        deny = (
            [real_path(self.style.expand_home(item, self.home)) for item in DEFAULT_DENY_READ] if self.standard else []
        )
        return PathRules(
            style=self.style,
            read=list(self.roots),
            write=list(self.roots),
            deny=deny,
            protected=self.is_protected if self.standard else None,
            exempt=self.framework_dirs,
        )

    def can_read(self, path: str) -> bool:
        return self.rules.can_read(path)

    def can_write(self, path: str) -> bool:
        return self.rules.can_write(path)

    def checked_scope(self, scope: Scope) -> Scope:
        scope = replace(
            scope,
            workspace=real_path(scope.workspace),
            cwd=real_path(scope.cwd),
            tmp=real_path(scope.tmp),
            readable=[real_path(path) for path in scope.readable],
        )
        roots = list(self.roots)
        if not any(self._inside(scope.workspace, root) for root in roots):
            raise PermissionError(f"工作区 {scope.workspace} 不在设备开放的目录内")
        if not any(self._inside(scope.cwd, root) for root in roots):
            raise PermissionError(f"工作目录 {scope.cwd} 不在设备允许的目录内")
        if not self._inside(scope.tmp, real_path(os.path.join(scope.data_dir, "tmp"))):
            raise PermissionError(f"临时目录 {scope.tmp} 不在 {scope.data_dir}/tmp 内")

        allowed = roots + [real_path(os.path.join(scope.data_dir, "skills"))]
        readable = [path for path in scope.readable if any(self._inside(path, root) for root in allowed)]
        return replace(scope, readable=readable)

    def effective_sandbox(self, backend: Sandbox, scope: Scope) -> Sandbox:
        def resolve(path: str) -> str:
            return real_path(scope.absolute(path))

        write = inside_roots(list(backend.write), list(self.roots), resolve, self.style)
        read = inside_roots(list(backend.read), list(self.roots), resolve, self.style)
        network = effective_network(backend, self.node_sandbox)
        kind = effective_kind(backend, self.node_sandbox)
        rules = {
            "write": write,
            "read": read,
            "deny_read": _union(list(DEFAULT_DENY_READ), backend.deny_read)
            if self.standard
            else list(backend.deny_read),
            "protect": list(backend.protect),
        }
        if kind == "srt":
            if network is True:
                raise PermissionError("设备使用 srt 沙箱时须列出允许访问的域名；请指定 --network")

            # 后端设置了这几项时直接拒绝，不悄悄忽略
            if isinstance(backend, SRT) and (backend.binary != "srt" or backend.nested or backend.settings):
                raise PermissionError(
                    "设备不接受后端指定的 srt 程序位置、nested 或额外配置；"
                    "这些由设备所有者在启动设备守护进程时用 --srt-binary、--srt-nested、--srt-settings 决定"
                )
            return SRT(
                network=network or [],
                **rules,
                binary=self.srt_binary,
                nested=self.srt_nested,
                settings=dict(self.srt_settings),
            )
        return NoSandbox()

    def restrict(self, sandbox: Sandbox, scope: Scope, unsandboxed: bool = False) -> tuple[Sandbox, Scope]:
        scope = self.checked_scope(scope)
        if unsandboxed:
            if not unsandboxed_allowed(self.node_sandbox):
                raise PermissionError("该设备不允许在沙箱外执行命令；设备所有者需启用 --allow-unsandboxed")
            return NoSandbox(), scope
        return self.effective_sandbox(sandbox, scope), scope


class FileRules(helper.Rules):
    def __init__(self, policy: DevicePolicy) -> None:
        self.policy = policy
        self._rules = policy.rules

    def check_read(self, path: str) -> None:
        if not self._rules.can_read(path):
            raise PermissionError(f"设备不允许读取 {path}")

    def check_write(self, path: str) -> None:
        if not self._rules.can_write(path):
            raise PermissionError(f"设备不允许写入 {path}")

    def check_remove(self, path: str) -> None:
        policy = self.policy
        protected = [*policy.roots, policy.data_dir, *policy.framework_dirs]
        if any(policy.style.inside(item, path) for item in protected):
            raise PermissionError(f"设备不允许删除或移动 {path}")

    def check_moved_tree(self, source: str, target: str) -> None:
        # 防止先在别处建好 hooks/pre-commit，再把目录移成 .git/hooks
        policy = self.policy
        if not policy.standard or not os.path.isdir(source) or os.path.islink(source):
            return

        for directory, names, filenames in os.walk(source):
            for name in names + filenames:
                moved = os.path.join(target, os.path.relpath(os.path.join(directory, name), source))
                if policy.is_protected(moved):
                    raise PermissionError(
                        f"设备不允许将 {source} 移动到 {target}：其中有文件将落在钩子或配置文件的位置"
                    )

    def visible(self, path: str) -> bool:
        # 不列出指向范围外的链接，以免泄露外部文件的大小、时间和位置
        return self._rules.can_read(path)
