from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any

import work_agent_sdk.host.files.helper as helper
import work_agent_sdk.host.files.scan as scan
from work_agent_sdk.host.browser import BrowserOptions, start_browser, stop_browser
from work_agent_sdk.host.commands.env import inherited_variables
from work_agent_sdk.host.commands.process import OutputChunk, Stdin
from work_agent_sdk.host.commands.run import Command, local_shell, run_command
from work_agent_sdk.host.files.paths import NodePaths, local_style, local_system
from work_agent_sdk.host.screen.apps import AppsBackend, local_apps
from work_agent_sdk.host.screen.backends import (
    ScreenBackend,
    default_display,
    local_screen,
)
from work_agent_sdk.host.screen.executor import start_escape_listener
from work_agent_sdk.nodes.base import (
    DirectPort,
    Node,
    NodeInfo,
    PortForward,
    checked_env_vars,
)


class Local(Node):
    """
    The backend's own machine, with node name "local". Commands inherit only a few environment variables from the backend process (PATH, HOME, LANG, etc.).
    With esc_stop=True, a global Esc listener is registered to emergency-stop computer operations (requires pynput).
    """

    name = "local"

    def __init__(self, *, env: dict[str, str] | None = None, esc_stop: bool = False) -> None:
        super().__init__()
        self.variables = checked_env_vars(env)
        self.esc_stop = esc_stop
        self._listener: Any = None

    def __repr__(self) -> str:
        return "Local()"

    async def start(self) -> None:
        paths = NodePaths(os.path.expanduser("~"), local_style())
        await asyncio.to_thread(helper.ensure_private_dir, paths.data_dir)

        # Clean up transfer files left behind by earlier interrupted transfers (several backend processes may share a machine, so only those untouched for a long time)
        await asyncio.to_thread(helper.clean_transfers, paths.tmp_root)

        if self.esc_stop and self._listener is None:
            self._listener = start_escape_listener(self._escape_pressed)

    def _escape_pressed(self) -> None:
        # This listens on the display this process runs on; right after the framework sends keyboard input to it, key presses may come from the framework itself
        own = self._executors.get(default_display())
        if own is None or not own.sent_input_recently():
            self.stop_screens()

    async def close(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    async def info(self) -> NodeInfo:
        return self.known_info()

    def known_info(self) -> NodeInfo:
        return NodeInfo(os=local_system(), shell=local_shell(), home=os.path.expanduser("~"))

    async def exec(self, command: Command, stdin: Stdin = None) -> AsyncIterator[OutputChunk]:
        variables = {**inherited_variables(), **self.variables}
        async for chunk in run_command(command, stdin, variables=variables):
            yield chunk

    async def file_op(self, op: str, **arguments: Any) -> Any:
        return await asyncio.to_thread(helper.run_op, op, arguments)

    async def read_block(self, path: str, offset: int, size: int) -> bytes:
        return await asyncio.to_thread(helper.read_block, helper.UNRESTRICTED, path, offset, size)

    async def write_block(self, path: str, offset: int, data: bytes) -> None:
        await asyncio.to_thread(helper.write_block, helper.UNRESTRICTED, path, offset, data)

    async def tree_hash(self, path: str) -> str | None:
        if not os.path.exists(os.path.expanduser(path)):
            return None
        return await asyncio.to_thread(scan.tree_hash, path)

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
        return await asyncio.to_thread(
            scan.find_manifests, workspace, roots, manifest, max_size, unchanged=unchanged, read=read
        )

    async def start_browser(self, options: BrowserOptions) -> int:
        return await start_browser(options)

    async def stop_browser(self, profile: str) -> None:
        await stop_browser(profile)

    async def forward_port(self, port: int) -> PortForward:
        return DirectPort(port)

    def screen_display(self, requested: str | None) -> str | None:
        return requested or default_display()

    def screen(self, display: str | None) -> ScreenBackend:
        return local_screen(display)

    def apps(self, display: str | None) -> AppsBackend:
        return local_apps(display)
