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
    # Exposed directories (real paths)
    roots: list[str]
    sandbox: str = "none"
    # Domain upper bound; None means no bound
    network: list[str] | None = None
    # Whether commands approved by the backend may run outside the sandbox (only meaningful when the device has a sandbox configured)
    allow_unsandboxed: bool = False
    # Protection template: standard or none (see protect.py)
    protect: str = "standard"
    # The following decide which program runs outside the sandbox and how strong the sandbox is; only the device owner decides them
    srt_binary: str = "srt"
    srt_nested: bool = False
    srt_settings: dict[str, Any] = field(default_factory=dict)
    home: str = field(default_factory=lambda: os.path.expanduser("~"))
    # The device daemon runs on this machine, so paths follow this machine's OS
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
        # Join names under the data directory with symlinks already resolved (these directories themselves aren't resolved again, so replacing them with links can't turn other locations into framework directories)
        return [os.path.join(self.data_dir, os.path.basename(path)) for path in self.paths.framework_dirs]

    @property
    def standard(self) -> bool:
        return self.protect == "standard"

    def is_protected(self, path: str) -> bool:
        return self.standard and is_protected(self.style, path)

    @property
    def rules(self) -> PathRules:
        # The standard template blocks writes to hooks and shell config: scripts written there would run outside the sandbox the next time the device owner does something
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
            raise PermissionError(f"Workspace {scope.workspace} is not inside a directory exposed by the device")
        if not any(self._inside(scope.cwd, root) for root in roots):
            raise PermissionError(f"Working directory {scope.cwd} is not inside a directory the device allows")
        if not self._inside(scope.tmp, real_path(os.path.join(scope.data_dir, "tmp"))):
            raise PermissionError(f"Temporary directory {scope.tmp} is not inside {scope.data_dir}/tmp")

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
            # If the backend sets any of these, raise an error instead of ignoring them
            if isinstance(backend, SRT) and (backend.binary != "srt" or backend.nested or backend.settings):
                raise PermissionError(
                    "The device doesn't accept an srt program location, nested mode or extra settings from the backend; "
                    "the device owner decides these with --srt-binary, --srt-nested and --srt-settings when starting the device daemon"
                )
            return SRT(
                network=network,
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
                raise PermissionError("This device doesn't allow running commands outside the sandbox; the device owner must enable --allow-unsandboxed")
            return NoSandbox(), scope
        return self.effective_sandbox(sandbox, scope), scope


class FileRules(helper.Rules):
    def __init__(self, policy: DevicePolicy) -> None:
        self.policy = policy
        self._rules = policy.rules

    def check_read(self, path: str) -> None:
        if not self._rules.can_read(path):
            raise PermissionError(f"The device doesn't allow reading {path}")

    def check_write(self, path: str) -> None:
        if not self._rules.can_write(path):
            raise PermissionError(f"The device doesn't allow writing {path}")

    def check_remove(self, path: str) -> None:
        policy = self.policy
        protected = [*policy.roots, policy.data_dir, *policy.framework_dirs]
        if any(policy.style.inside(item, path) for item in protected):
            raise PermissionError(f"The device doesn't allow deleting or moving {path}")

    def check_moved_tree(self, source: str, target: str) -> None:
        # Prevent creating hooks/pre-commit somewhere else first and then moving that directory to .git/hooks
        policy = self.policy
        if not policy.standard or not os.path.isdir(source) or os.path.islink(source):
            return

        for directory, names, filenames in os.walk(source):
            for name in names + filenames:
                moved = os.path.join(target, os.path.relpath(os.path.join(directory, name), source))
                if policy.is_protected(moved):
                    raise PermissionError(
                        f"The device doesn't allow moving {source} to {target}: some files in it would land where hooks or config files go"
                    )

    def visible(self, path: str) -> bool:
        # Don't list links pointing outside the allowed scope, to avoid leaking the size, time and location of outside files
        return self._rules.can_read(path)
