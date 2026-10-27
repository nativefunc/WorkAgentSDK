from __future__ import annotations

import re
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from typing import Any

import work_agent_sdk.host.files.paths as paths
import work_agent_sdk.nodes.transfer as transfer
from work_agent_sdk.host.browser import BrowserOptions
from work_agent_sdk.host.commands.process import (
    OutputChunk,
    RunResult,
    Stdin,
    collect_output,
)
from work_agent_sdk.host.commands.run import Command
from work_agent_sdk.host.commands.sandbox import NodeSandbox
from work_agent_sdk.host.files.info import FileInfo
from work_agent_sdk.host.screen.apps import AppsBackend
from work_agent_sdk.host.screen.backends import ScreenBackend
from work_agent_sdk.host.screen.executor import ScreenExecutor
from work_agent_sdk.host.screen.policy import DeviceCeiling

ENV_VAR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class NodeInfo:
    os: str
    shell: str
    home: str
    # Whether commands can run on this node: not when the device only exposes file read/write (no --sandbox)
    commands: bool = True
    # Sandbox set by the device owner; None means the node imposes no limits (e.g. the backend's own machine) and the backend's workspace configuration applies fully
    sandbox: NodeSandbox | None = None
    # Directories exposed by the device owner (real paths); None means unrestricted
    roots: list[str] | None = None
    # Cap the device sets for the screen; None means no cap (e.g. the backend's own machine) or the screen isn't exposed
    screen_ceiling: DeviceCeiling | None = None

    @property
    def style(self) -> paths.PathStyle:
        return paths.PathStyle(self.os)

    @property
    def node_paths(self) -> paths.NodePaths:
        return paths.NodePaths(self.home, self.style)


def checked_env_vars(env: dict[str, str] | None) -> dict[str, str]:
    for name in env or {}:
        if not ENV_VAR_NAME.fullmatch(name):
            raise ValueError(f"Invalid environment variable name: {name!r}")
    return dict(env or {})


class Node:
    """A node: the backend's own machine (Local) or a machine running the device daemon (Device). Not meant to be subclassed by developers."""

    name: str = ""

    def __init__(self) -> None:
        self._executors: dict[str | None, ScreenExecutor] = {}
        # After an emergency stop, pause all screens (including displays used later) until the process restarts
        self._screens_stopped = False

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        pass

    def _missing(self, what: str) -> NotImplementedError:
        return NotImplementedError(f"{self!r} doesn't implement {what}")

    async def info(self) -> NodeInfo:
        raise self._missing("info")

    def known_info(self) -> NodeInfo | None:
        """Node information available without talking to the node; None if not yet available."""
        return None

    async def check_workspace(self, path: str) -> None:
        """Check whether a workspace can be placed at path on this node; raise ConfigError if not."""

    def exec(self, command: Command, stdin: Stdin = None) -> AsyncIterator[OutputChunk]:
        """Run a command to completion; the last chunk is the exit code. When the caller stops iterating, the process on the node must be terminated."""
        raise self._missing("running commands")

    async def run(self, command: Command, stdin: Stdin = None) -> RunResult:
        return await collect_output(self.exec(command, stdin))

    async def file_op(self, op: str, **arguments: Any) -> Any:
        """Perform a file operation, raising the matching OSError subclass on failure."""
        raise self._missing("file operations")

    async def read_block(self, path: str, offset: int, size: int) -> bytes:
        raise self._missing("file operations")

    async def write_block(self, path: str, offset: int, data: bytes) -> None:
        raise self._missing("file operations")

    async def stat(self, path: str) -> FileInfo:
        return FileInfo.from_dict(await self.file_op("stat", path=path))

    async def list_dir(self, path: str) -> list[FileInfo]:
        return [FileInfo.from_dict(item) for item in await self.file_op("list", path=path)]

    async def make_dir(self, path: str) -> None:
        await self.file_op("make_dir", path=path)

    async def remove(self, path: str) -> None:
        await self.file_op("remove", path=path)

    async def move(self, source: str, target: str) -> None:
        await self.file_op("move", source=source, target=target)

    async def write_file(self, path: str, data: bytes | AsyncIterable[bytes], *, executable: bool = False) -> FileInfo:
        info = await self.info()
        return FileInfo.from_dict(
            await transfer.upload(
                self, path, data, directory=info.node_paths.transfers, style=info.style, executable=executable
            )
        )

    async def tree_hash(self, path: str) -> str | None:
        raise self._missing("directory hashing")

    async def find_manifests(
        self,
        workspace: str,
        roots: list[str],
        manifest: str,
        max_size: int,
        *,
        unchanged: str | None = None,
        read: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        raise self._missing("finding skill files")

    async def start_browser(self, options: BrowserOptions) -> int:
        raise NotImplementedError(f"{self!r} doesn't expose a browser")

    async def stop_browser(self, profile: str) -> None:
        raise NotImplementedError(f"{self!r} doesn't expose a browser")

    async def forward_port(self, port: int) -> PortForward:
        raise NotImplementedError(f"{self!r} doesn't support connecting to a browser")

    def screen(self, display: str | None) -> ScreenBackend:
        raise NotImplementedError(f"{self!r} doesn't expose its screen")

    def apps(self, display: str | None) -> AppsBackend:
        """Return the node's app backend. By default apps can't be identified, so standard rules refuse input."""
        return AppsBackend()

    def screen_display(self, requested: str | None) -> str | None:
        """The display the session actually operates. Omitting it and explicitly specifying the same display must give the same result; control is separated by it."""
        return requested

    def executor(self, display: str | None = None) -> ScreenExecutor:
        if display not in self._executors:
            executor = ScreenExecutor(self.screen(display), self.apps(display))
            if self._screens_stopped:
                executor.emergency_stop()
            self._executors[display] = executor
        return self._executors[display]

    def stop_screens(self) -> None:
        """Emergency stop: abort actions in progress on all screens and pause all screens."""
        self._screens_stopped = True
        for executor in self._executors.values():
            executor.emergency_stop()

    async def computer(self, op: str, display: str | None = None, **arguments: Any) -> Any:
        return await self.executor(display).handle(op, arguments)


class PortForward:
    host = "127.0.0.1"
    local_port = 0

    @property
    def address(self) -> str:
        return f"{self.host}:{self.local_port}"

    async def close(self) -> None:
        pass


class DirectPort(PortForward):
    def __init__(self, port: int) -> None:
        self.local_port = port
