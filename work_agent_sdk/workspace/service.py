from __future__ import annotations

from typing import Any

import work_agent_sdk.strings.workspace as strings
from work_agent_sdk.core.errors import ConfigError
from work_agent_sdk.core.service import RunnerAPI, Service, SessionRef
from work_agent_sdk.core.tool import unwrap
from work_agent_sdk.host.commands.process import Stdin
from work_agent_sdk.host.commands.run import Command
from work_agent_sdk.host.commands.sandbox import (
    NoSandbox,
    Sandbox,
    effective_kind,
    effective_network,
    inside_roots,
    unsandboxed_allowed,
)
from work_agent_sdk.nodes.base import Node, NodeInfo, RunResult
from work_agent_sdk.nodes.files import FileHost, NodeHost, ScopedFiles
from work_agent_sdk.workspace.config import Workspace
from work_agent_sdk.workspace.processes import Process, Processes
from work_agent_sdk.workspace.sandboxed import SandboxHost
from work_agent_sdk.workspace.store import ProcessStore, SqliteProcessStore


class BoundWorkspace:
    """绑定到某个会话的工作区，即 ctx.workspace 与 await session.workspace() 返回的对象。"""

    def __init__(
        self,
        config: Workspace,
        node: Node,
        info: NodeInfo,
        *,
        session: SessionRef,
        processes: Processes,
        api: RunnerAPI,
        isolated: bool,
    ) -> None:
        self.config = config
        self.node = node
        self.info = info
        self.isolated = isolated
        self._session = session
        self._processes = processes
        self._api = api
        self.style = info.style
        self.paths = info.node_paths
        self.path = self.style.absolute(config.path, info.home)
        if self.style.is_root(self.path) or self.style.same(self.path, info.home):
            raise ConfigError(f"工作区不能是根目录或家目录：{config.path}；请指定一个项目目录")

        self.tmp = self.paths.tmp(session.root_id)
        self.skills_dir = self.paths.skills

        # 文件操作与 run 中的命令一样受工作区沙箱约束。框架或开发者以自身身份操作时直接用 self.node
        host: FileHost = (
            NodeHost(node, self.style, self.paths.transfers)
            if isinstance(self.sandbox, NoSandbox)
            else SandboxHost(self)
        )
        self.files = ScopedFiles(
            host,
            style=self.style,
            home=info.home,
            base=self.path,
            keep=[self.path],
        )

    def __repr__(self) -> str:
        return f"Workspace({self.path!r} on {self.config.node!r})"

    @property
    def node_name(self) -> str:
        return self.config.node

    @property
    def sandbox(self) -> Sandbox:
        if self.config.sandbox is None:
            if not self.isolated:
                raise ConfigError(
                    f"工作区 {self.config.path} 未配置沙箱，且节点 {self.config.node} 不是隔离边界；"
                    "请传入 sandbox=SRT(...) 或 NoSandbox()"
                )
            return NoSandbox()
        return self.config.sandbox

    @property
    def description(self) -> str:
        return self.config.description

    def absolute(self, path: str) -> str:
        """将路径解析为绝对路径：相对路径以工作区为基准，~ 指节点上的家目录。"""
        return self.style.absolute(path, self.info.home, base=self.path)

    def resolve(self, path: str | None) -> str:
        """解析工作区内的路径：相对路径以工作区为基准，绝对路径须在工作区内（仅按字面判断）。"""
        if not path:
            return self.path

        resolved = self.absolute(path)
        if not self.style.inside(resolved, self.path):
            raise PermissionError(f"路径不在工作区内：{path}")
        return resolved

    def relative(self, path: str) -> str:
        """展示给模型的路径：工作区内的路径显示为相对路径。"""
        return self.style.relative(path, self.path)

    def command(
        self,
        line: str,
        *,
        cwd: str | None = None,
        timeout: float | None = None,
        unsandboxed: bool = False,
    ) -> Command:
        if not self.info.commands:
            raise PermissionError(
                f"节点 {self.config.node} 仅开放文件读写，不允许执行命令；设备守护进程需以 --sandbox 启动"
            )
        return Command(
            line=line,
            workspace=self.path,
            cwd=self.resolve(cwd),
            tmp=self.tmp,
            sandbox=NoSandbox() if unsandboxed else self.sandbox,
            readable=[self.skills_dir],
            timeout=timeout,
            unsandboxed=unsandboxed,
        )

    async def run(
        self,
        command: str,
        *,
        cwd: str | None = None,
        stdin: Stdin = None,
        timeout: float | None = 120,
        unsandboxed: bool = False,
    ) -> RunResult:
        """在工作区中执行命令并等待结束。unsandboxed=True 时在沙箱外执行，不经过审批，在设备上需设备所有者允许。"""
        spec = self.command(command, cwd=cwd, timeout=timeout, unsandboxed=unsandboxed)
        return await self.node.run(spec, stdin)

    async def start_process(
        self,
        command: str,
        *,
        cwd: str | None = None,
        background: bool = True,
        key: str | None = None,
        call_id: str | None = None,
        unsandboxed: bool = False,
        max_output_mb: float = 10,
    ) -> Process:
        """启动一个归属于该会话的进程，相同 key 的进程只启动一次。"""
        spec = self.command(command, cwd=cwd, unsandboxed=unsandboxed)
        return await self._processes.start(
            self._session.id,
            self.node,
            spec,
            node_name=self.config.node,
            path=self.path,
            background=background,
            key=key,
            call_id=call_id,
            max_output_mb=max_output_mb,
        )

    async def processes(self, *, children: bool = False) -> list[Process]:
        """该会话启动的进程；children=True 时包括子会话的进程。"""
        ids = [self._session.id]
        if children:
            ids += await self._api.descendants(self._session.id)

        return await self._processes.list(ids)

    async def process(self, process_id: str) -> Process:
        """获取该会话或其子会话的进程；进程不属于它们时抛出 LookupError。"""
        process = await self._processes.get(process_id)
        allowed = {self._session.id, *await self._api.descendants(self._session.id)}
        if process is None or process.session_id not in allowed:
            raise LookupError(f"当前会话中不存在进程 {process_id}")
        return process


class WorkspaceService(Service):
    """process_store 为进程记录的存储，省略时使用 data_dir/ext/workspace/workspace.db。"""

    provides = "workspace"

    def __init__(self, *, process_store: ProcessStore | None = None) -> None:
        self.process_store = process_store

    async def attach(self, api: RunnerAPI) -> None:
        await super().attach(api)
        if self.process_store is None:
            self.process_store = SqliteProcessStore(api.files("workspace") / "workspace.db")
        self.processes = Processes(api, self.process_store)

    def check(self, config: dict[str, Any]) -> None:
        workspace = Workspace.model_validate(config)
        if not self.api.nodes.known(workspace.node):
            raise ConfigError(f"工作区引用的节点 {workspace.node!r} 未登记；请通过 Runner(nodes=[...]) 登记该节点")
        if workspace.sandbox is None and not self.api.nodes.isolated(workspace.node):
            raise ConfigError(
                f"工作区 {workspace.path} 未配置沙箱，且节点 {workspace.node} 不是隔离边界；"
                "请传入 sandbox=SRT(...) 或 NoSandbox()"
            )

    async def bind(self, session: SessionRef) -> BoundWorkspace:
        config = Workspace.model_validate(session.resources["workspace"])
        node = await self.api.nodes.get(config.node, root_id=session.root_id)
        info = await node.info()
        if info.style.windows:
            # 命令按 POSIX shell 拼接，无法在 PowerShell 中执行
            raise ConfigError(
                f"节点 {config.node} 运行 Windows，不支持工作区；请在 Linux 机器、容器或虚拟机中部署设备守护进程作为工作区，"
                "或仅使用电脑操作和浏览器"
            )

        bound = BoundWorkspace(
            config,
            node,
            info,
            session=session,
            processes=self.processes,
            api=self.api,
            isolated=self.api.nodes.isolated(config.node),
        )
        await node.check_workspace(bound.path)
        await node.make_dir(bound.path)
        return bound

    async def ready(self, session: SessionRef) -> bool:
        config = Workspace.model_validate(session.resources["workspace"])
        return self.api.nodes.online(config.node, root_id=session.root_id) is not False

    async def facts(self, session: SessionRef) -> Any:
        """当前实际生效的工作区设置：节点所有者的沙箱设置与后端配置合并，规则与执行命令时一致。"""
        config = Workspace.model_validate(session.resources["workspace"])
        info = self.api.nodes.cached_info(config.node, root_id=session.root_id)
        facts: dict[str, Any] = {
            "node": config.node,
            "online": self.api.nodes.online(config.node, root_id=session.root_id),
            "path": info.style.absolute(config.path, info.home) if info is not None else config.path,
        }
        if info is not None:
            facts.update(os=info.os, shell=info.shell, commands=info.commands)
        if info is None or info.commands:
            facts.update(self._sandbox_facts(session, config, info))

        facts["shared_folders"] = self.api.nodes.shared_folders(config.node)
        if config.description:
            facts["description"] = config.description
        return facts

    def _sandbox_facts(self, session: SessionRef, config: Workspace, info: NodeInfo | None) -> dict[str, Any]:
        backend: Sandbox | None = config.sandbox or (NoSandbox() if self.api.nodes.isolated(config.node) else None)
        if backend is None:
            return {}  # 配置不完整，绑定工作区时报错

        node = info.sandbox if info is not None else None
        if effective_kind(backend, node) != "srt":
            return {"sandbox": "none"}

        network = effective_network(backend, node)
        return {
            "sandbox": "srt",
            "writable": self._writable(session, config, info, list(backend.write)),
            "domains": network,
            "unsandboxed": self._shell_allows_unsandboxed(session) and unsandboxed_allowed(node),
        }

    @staticmethod
    def _writable(session: SessionRef, config: Workspace, info: NodeInfo | None, paths: list[str]) -> list[str]:
        if info is None:
            return [config.path, "$TMPDIR", *paths]

        style = info.style
        workspace = style.absolute(config.path, info.home)
        extra = [style.absolute(path, info.home, base=workspace) for path in paths]
        if info.roots is not None:
            extra = inside_roots(extra, info.roots, lambda path: path, style)
        return [workspace, info.node_paths.tmp(session.root_id), *extra]

    @staticmethod
    def _shell_allows_unsandboxed(session: SessionRef) -> bool:
        from work_agent_sdk.workspace.shell import Shell

        return any(
            isinstance(unwrap(toolset), Shell) and unwrap(toolset).allow_unsandboxed for toolset in session.toolsets
        )

    def render(self, facts: Any) -> str:
        items: list[tuple[str, str]] = [(strings.FACTS_NODE, facts["node"])]
        if facts.get("online") is not None:
            items.append((strings.FACTS_STATUS, strings.FACTS_ONLINE if facts["online"] else strings.FACTS_OFFLINE))
        if facts.get("os"):
            items.append((strings.FACTS_OS, facts["os"]))
            items.append((strings.FACTS_SHELL, facts.get("shell") or ""))

        items.append((strings.FACTS_PATH, facts["path"]))
        if "commands" in facts:
            commands = strings.FACTS_ALLOWED if facts["commands"] else strings.FACTS_NOT_ALLOWED
            items.append((strings.FACTS_COMMANDS, commands))

        if facts.get("sandbox") == "none":
            items.append((strings.FACTS_SANDBOX, strings.FACTS_SANDBOX_NONE))
        elif facts.get("sandbox") == "srt":
            join = strings.FACTS_SEPARATOR.join
            domains = facts["domains"]
            if domains is True:
                domains_text = strings.FACTS_DOMAINS_ANY
            else:
                domains_text = join(domains or []) or strings.FACTS_DOMAINS_NONE

            unsandboxed = strings.FACTS_UNSANDBOXED_ALLOWED if facts["unsandboxed"] else strings.FACTS_NOT_ALLOWED
            items.append((strings.FACTS_SANDBOX, "srt"))
            items.append((strings.FACTS_WRITABLE, join(facts["writable"])))
            items.append((strings.FACTS_DOMAINS, domains_text))
            items.append((strings.FACTS_UNSANDBOXED, unsandboxed))

        for name, path in facts.get("shared_folders") or []:
            items.append((strings.FACTS_SHARED_FOLDER, strings.FACTS_SHARED_FOLDER_VALUE.format(name=name, path=path)))
        if facts.get("description"):
            items.append((strings.FACTS_DESCRIPTION, facts["description"]))

        lines = [strings.FACTS_ITEM.format(name=name, value=value) for name, value in items]
        return "\n".join([strings.FACTS_TITLE, *lines])

    async def runner_started(self) -> None:
        await self.processes.end_leftovers()

    async def runner_stopped(self) -> None:
        await self.processes.close()
        if self.process_store is not None:
            await self.process_store.close()

    async def call_cancelled(self, session: SessionRef, call_id: str) -> None:
        await self.processes.kill_call(session.id, call_id)

    async def session_stopped(self, session: SessionRef, everything: bool) -> None:
        if everything:
            await self.processes.kill_session(session.id, background_only=True)

    async def session_closing(self, session: SessionRef) -> None:
        await self.processes.kill_session(session.id)

    async def session_deleted(self, session: SessionRef) -> None:
        await self.processes.delete_session(session.id)

        if session.parent_id is None and "workspace" in session.resources:
            config = Workspace.model_validate(session.resources["workspace"])
            try:
                node = await self.api.nodes.get(config.node, root_id=session.root_id, wait=False)
                info = await node.info()
                await node.remove(info.node_paths.tmp(session.root_id))
            except Exception:
                pass
