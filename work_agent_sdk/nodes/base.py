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

ENV_VAR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class NodeInfo:
    os: str
    shell: str
    home: str
    # 能否在该节点上执行命令：设备仅开放文件读写（未指定 --sandbox）时不能
    commands: bool = True
    # 节点所有者设置的沙箱；None 表示节点不设限制（如后端本机），完全按后端的工作区配置执行
    sandbox: NodeSandbox | None = None
    # 节点所有者开放的目录（真实路径）；None 表示不限制
    roots: list[str] | None = None

    @property
    def style(self) -> paths.PathStyle:
        return paths.PathStyle(self.os)

    @property
    def node_paths(self) -> paths.NodePaths:
        return paths.NodePaths(self.home, self.style)


def checked_env_vars(env: dict[str, str] | None) -> dict[str, str]:
    for name in env or {}:
        if not ENV_VAR_NAME.fullmatch(name):
            raise ValueError(f"环境变量名不合法：{name!r}")
    return dict(env or {})


class Node:
    """节点：后端本机（Local）或运行设备守护进程的机器（Device）。不供开发者继承。"""

    name: str = ""

    def __init__(self) -> None:
        self._executors: dict[str | None, ScreenExecutor] = {}
        # 急停后暂停全部屏幕（包括此后才使用的桌面），直至进程重启
        self._screens_stopped = False

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        pass

    def _missing(self, what: str) -> NotImplementedError:
        return NotImplementedError(f"{self!r} 未实现{what}")

    async def info(self) -> NodeInfo:
        raise self._missing("info")

    def known_info(self) -> NodeInfo | None:
        """无需与节点通信即可得到的节点信息；尚未得到时返回 None。"""
        return None

    async def check_workspace(self, path: str) -> None:
        """检查能否在该节点的 path 处放置工作区，不能时抛出 ConfigError。"""

    def exec(self, command: Command, stdin: Stdin = None) -> AsyncIterator[OutputChunk]:
        """执行命令直至结束，最后一段为退出码。调用方停止迭代时须终止节点上的进程。"""
        raise self._missing("执行命令")

    async def run(self, command: Command, stdin: Stdin = None) -> RunResult:
        return await collect_output(self.exec(command, stdin))

    async def file_op(self, op: str, **arguments: Any) -> Any:
        """执行一项文件操作，出错时抛出对应的 OSError 子类。"""
        raise self._missing("文件操作")

    async def read_block(self, path: str, offset: int, size: int) -> bytes:
        raise self._missing("文件操作")

    async def write_block(self, path: str, offset: int, data: bytes) -> None:
        raise self._missing("文件操作")

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
        raise self._missing("目录哈希")

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
        raise self._missing("查找技能文件")

    async def start_browser(self, options: BrowserOptions) -> int:
        raise NotImplementedError(f"{self!r} 未开放浏览器")

    async def stop_browser(self, profile: str) -> None:
        raise NotImplementedError(f"{self!r} 未开放浏览器")

    async def forward_port(self, port: int) -> PortForward:
        raise NotImplementedError(f"{self!r} 不支持连接浏览器")

    def screen(self, display: str | None) -> ScreenBackend:
        raise NotImplementedError(f"{self!r} 未开放屏幕")

    def apps(self, display: str | None) -> AppsBackend:
        """返回节点的应用后端。默认无法识别应用，standard 规则据此拒绝输入。"""
        return AppsBackend()

    def screen_display(self, requested: str | None) -> str | None:
        """会话实际操作的桌面。省略与显式指定同一块桌面时须得到相同的结果，控制权按它区分。"""
        return requested

    def executor(self, display: str | None = None) -> ScreenExecutor:
        if display not in self._executors:
            executor = ScreenExecutor(self.screen(display), self.apps(display))
            if self._screens_stopped:
                executor.emergency_stop()
            self._executors[display] = executor
        return self._executors[display]

    def stop_screens(self) -> None:
        """急停：中止全部屏幕上正在执行的动作，并暂停全部屏幕。"""
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
