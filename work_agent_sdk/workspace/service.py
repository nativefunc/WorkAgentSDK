from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

import work_agent_sdk.strings.workspace as strings
from work_agent_sdk.core.errors import ConfigError
from work_agent_sdk.core.service import RunnerAPI, Service, SessionRef
from work_agent_sdk.core.tool import unwrap
from work_agent_sdk.host.commands.process import Stdin
from work_agent_sdk.host.commands.run import Command
from work_agent_sdk.host.commands.sandbox import (
    SRT,
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


class _FilesHost:
    """The sandbox can change during a session, so each file operation picks based on the current sandbox: operate on the node directly, or inside the sandbox."""

    def __init__(self, workspace: BoundWorkspace) -> None:
        self._workspace = workspace
        self._direct = NodeHost(workspace.node, workspace.style, workspace.paths.transfers)
        self._sandboxed = SandboxHost(workspace)

    def _host(self) -> FileHost:
        return self._direct if isinstance(self._workspace.sandbox, NoSandbox) else self._sandboxed

    async def op(self, name: str, **arguments: Any) -> Any:
        return await self._host().op(name, **arguments)

    def read(self, path: str, max_size: int | None) -> AsyncIterator[bytes]:
        return self._host().read(path, max_size)

    async def write(self, path: str, data: bytes | AsyncIterable[bytes], max_size: int | None) -> dict[str, Any]:
        return await self._host().write(path, data, max_size)


class BoundWorkspace:
    """The workspace bound to a session, i.e. the object returned by ctx.workspace and await session.workspace()."""

    def __init__(
        self,
        config: Workspace,
        node: Node,
        info: NodeInfo,
        *,
        session: SessionRef,
        processes: Processes,
        api: RunnerAPI,
        service: WorkspaceService,
    ) -> None:
        self.config = config
        self.node = node
        self.info = info
        self._session = session
        self._processes = processes
        self._api = api
        self._service = service
        self.style = info.style
        self.paths = info.node_paths
        self.path = self.style.absolute(config.path, info.home)
        if self.style.is_root(self.path) or self.style.same(self.path, info.home):
            raise ConfigError(f"The workspace can't be the root directory or the user's home directory: {config.path}; specify a project directory")

        self.tmp = self.paths.tmp(session.root_id)
        self.skills_dir = self.paths.skills

        # File operations are subject to the workspace sandbox, like commands in run. When the framework or developer acts on its own behalf, use self.node directly
        self.files = ScopedFiles(
            _FilesHost(self),
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
        return self._service.current_sandbox(self._session.root_id, self.config)

    async def get_sandbox(self) -> Sandbox:
        return self.sandbox.model_copy(deep=True)

    async def set_sandbox(self, sandbox: Sandbox) -> None:
        if not isinstance(sandbox, (SRT, NoSandbox)):
            raise TypeError(f"sandbox must be SRT(...) or NoSandbox(), got {type(sandbox).__name__}")
        await self._service.set_sandbox(self._session, sandbox.model_copy(deep=True))

    @property
    def description(self) -> str:
        return self.config.description

    def absolute(self, path: str) -> str:
        """Resolve a path to an absolute path: relative paths are relative to the workspace, and ~ is the user's home directory on the node."""
        return self.style.absolute(path, self.info.home, base=self.path)

    def resolve(self, path: str | None) -> str:
        """Resolve a path inside the workspace: relative paths are relative to the workspace, and absolute paths must be inside the workspace (checked literally)."""
        if not path:
            return self.path

        resolved = self.absolute(path)
        if not self.style.inside(resolved, self.path):
            raise PermissionError(f"Path is not inside the workspace: {path}")
        return resolved

    def relative(self, path: str) -> str:
        """The path shown to the LLM: paths inside the workspace are shown as relative paths."""
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
                f"Node {self.config.node} only exposes file read/write and doesn't allow running commands; the device daemon must be started with --sandbox"
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
        """Run a command in the workspace and wait for it to finish. With unsandboxed=True it runs outside the sandbox without approval; on a device the device owner must allow it."""
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
        """Start a process belonging to this session; a process with the same key is only started once."""
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
        """Processes started by this session; with children=True, includes child sessions' processes."""
        ids = [self._session.id]
        if children:
            ids += await self._api.descendants(self._session.id)

        return await self._processes.list(ids)

    async def process(self, process_id: str) -> Process:
        """Get a process of this session or its child sessions; raises LookupError if it belongs to neither."""
        process = await self._processes.get(process_id)
        allowed = {self._session.id, *await self._api.descendants(self._session.id)}
        if process is None or process.session_id not in allowed:
            raise LookupError(f"Process {process_id} doesn't exist in the current session")
        return process


class WorkspaceService(Service):
    """process_store is the storage for process records; uses data_dir/ext/workspace/workspace.db when omitted."""

    provides = "workspace"

    def __init__(self, *, process_store: ProcessStore | None = None) -> None:
        self.process_store = process_store

        # The current sandbox of each session tree (taken from the configuration saved in the top-level session), updated by set_sandbox
        self._sandboxes: dict[str, Sandbox] = {}

    async def attach(self, api: RunnerAPI) -> None:
        await super().attach(api)
        if self.process_store is None:
            self.process_store = SqliteProcessStore(api.files("workspace") / "workspace.db")
        self.processes = Processes(api, self.process_store)

    def check(self, config: dict[str, Any]) -> None:
        workspace = Workspace.model_validate(config)
        if not self.api.nodes.known(workspace.node):
            raise ConfigError(f"Node {workspace.node!r} referenced by the workspace is not registered; register it with Runner(nodes=[...])")

    def current_sandbox(self, root_id: str, config: Workspace) -> Sandbox:
        return self._sandboxes.get(root_id, config.sandbox)

    async def _load_sandbox(self, session: SessionRef) -> None:
        # Child sessions copied the configuration at creation, and later changes are only saved in the top-level session, so the top-level session always wins
        if session.root_id in self._sandboxes:
            return

        root = session if session.parent_id is None else await self.api.session(session.root_id)
        resources = (root or session).resources
        if "workspace" in resources:
            self._sandboxes[session.root_id] = Workspace.model_validate(resources["workspace"]).sandbox

    async def set_sandbox(self, session: SessionRef, sandbox: Sandbox) -> None:
        root = session if session.parent_id is None else await self.api.session(session.root_id)
        if root is None:
            raise LookupError(f"Session {session.root_id} does not exist")

        config = Workspace.model_validate(root.resources["workspace"])
        config.sandbox = sandbox
        await self.api.update_resource(session.root_id, "workspace", config.to_config())
        self._sandboxes[session.root_id] = sandbox

    async def bind(self, session: SessionRef) -> BoundWorkspace:
        await self._load_sandbox(session)
        config = Workspace.model_validate(session.resources["workspace"])
        node = await self.api.nodes.get(config.node, root_id=session.root_id)
        info = await node.info()
        if info.style.windows:
            # Commands are assembled for a POSIX shell and can't run in PowerShell
            raise ConfigError(
                f"Node {config.node} runs Windows, which doesn't support workspaces; deploy the device daemon as a workspace on a Linux machine, container or virtual machine, "
                "or use only computer control and the browser"
            )

        bound = BoundWorkspace(
            config,
            node,
            info,
            session=session,
            processes=self.processes,
            api=self.api,
            service=self,
        )
        await node.check_workspace(bound.path)
        await node.make_dir(bound.path)
        return bound

    async def ready(self, session: SessionRef) -> bool:
        config = Workspace.model_validate(session.resources["workspace"])
        return self.api.nodes.online(config.node, root_id=session.root_id) is not False

    async def facts(self, session: SessionRef) -> Any:
        """Return the workspace settings described to the model: the device owner's sandbox settings merged with the backend configuration, matching the rules used when running commands."""
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
            await self._load_sandbox(session)
            facts.update(self._sandbox_facts(session, config, info))

        facts["shared_folders"] = self.api.nodes.shared_folders(config.node)
        if config.description:
            facts["description"] = config.description
        return facts

    def _sandbox_facts(self, session: SessionRef, config: Workspace, info: NodeInfo | None) -> dict[str, Any]:
        backend = self.current_sandbox(session.root_id, config)
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
            domains_text = join(facts["domains"]) or strings.FACTS_DOMAINS_NONE

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

        if session.parent_id is None:
            self._sandboxes.pop(session.root_id, None)

        if session.parent_id is None and "workspace" in session.resources:
            config = Workspace.model_validate(session.resources["workspace"])
            try:
                node = await self.api.nodes.get(config.node, root_id=session.root_id, wait=False)
                info = await node.info()
                await node.remove(info.node_paths.tmp(session.root_id))
            except Exception:
                pass
