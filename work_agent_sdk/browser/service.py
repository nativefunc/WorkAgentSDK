from __future__ import annotations

import collections
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import work_agent_sdk.strings.browser as strings
from work_agent_sdk.browser.actions import BROWSER_USER_INPUT
from work_agent_sdk.browser.config import Browser, BrowserPolicy
from work_agent_sdk.browser.driver.connections import BrowserContexts
from work_agent_sdk.browser.driver.contexts import BrowserContext
from work_agent_sdk.browser.driver.downloads import DownloadPlace, resolve_place
from work_agent_sdk.browser.driver.live import BrowserFrame, follow
from work_agent_sdk.browser.driver.pages import PageError
from work_agent_sdk.core.coordinates import model_space, to_image
from work_agent_sdk.core.errors import ConfigError
from work_agent_sdk.core.messages import CustomMessage
from work_agent_sdk.core.service import RunnerAPI, Service, SessionRef
from work_agent_sdk.workspace.config import Workspace


class BoundBrowser:
    """The browser bound to a session, i.e. the object returned by ctx.browser and await session.browser()."""

    def __init__(self, config: Browser, session: SessionRef, service: BrowserService) -> None:
        self.config = config
        self.session_ref = session
        self._service = service
        self._place: DownloadPlace | None = None

    def __repr__(self) -> str:
        return f"Browser(node={self.config.node!r}, cdp={bool(self.config.cdp)})"

    @property
    def policy(self) -> BrowserPolicy:
        return self.config.policy

    @property
    def description(self) -> str:
        return self.config.description

    @property
    def node(self) -> str | None:
        return self.config.node

    def paused(self) -> bool:
        """Whether the device owner has paused browser operations."""
        return bool(self.config.node) and self._service.api.nodes.paused(
            self.config.node, root_id=self.session_ref.root_id
        )

    @property
    def owner(self) -> str:
        return self.session_ref.id

    async def _workspace(self) -> Any:
        if "workspace" not in self.session_ref.resources:
            return None
        return await self._service.api.resource(self.session_ref.id, "workspace")

    async def place(self) -> DownloadPlace:
        if self._place is None:
            self._place = await resolve_place(self._service.api.nodes, self.config, self.session_ref.root_id)
        return self._place

    async def browser_context(self) -> BrowserContext:
        return await self._service.contexts.context_for(self.session_ref.root_id, self.config, await self.place())

    async def viewport(self, tab_id: str | None = None) -> tuple[int, int]:
        """Size of the tab's visible area (CSS pixels), i.e. the size of the model's screenshots; uses the current tab when tab_id is omitted."""
        return await (await self.browser_context()).viewport(self.owner, tab_id)

    async def perform(self, member: str, args: dict[str, Any]) -> dict[str, Any]:
        """Perform an action with the same arguments as the model's tool. Only checks URL rules; doesn't check whether the action is enabled or ask the user to confirm. Raises PermissionError when a URL rule is violated."""
        context = await self.browser_context()
        args = await self._page_coordinates(args)
        if member == "file_upload":
            paths, directory = await self._upload_paths(args)
            args = {**args, "_paths": paths, "_directory": directory}

        return await context.perform(self.owner, member, args)

    async def state(self) -> dict[str, Any]:
        context = await self.browser_context()
        return await context.with_titles(context.state(self.owner))

    async def targets(self, call: Any, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        For hooks: return what this action actually targets (page URL, element, link or form submission URL, whether it submits).
        The argument is the call received by before_tool, or (action name, arguments).
        """
        if args is None:
            member, args = call.name.removeprefix("browser_"), call.args
        else:
            member = call

        args = await self._page_coordinates(args)
        return await (await self.browser_context()).targets(self.owner, member, args)

    async def _page_coordinates(self, args: dict[str, Any]) -> dict[str, Any]:
        model = await self._service.api.model(self.session_ref.id)
        if model.screen_coordinates is None:
            return args

        viewport = await self.viewport(args.get("tab_id"))
        space = model_space(model, viewport)
        converted = dict(args)
        for field in ("target", "from"):
            target = args.get(field)
            if isinstance(target, dict) and target.get("type") == "coordinate":
                x, y = to_image((target["x"], target["y"]), space, viewport)
                converted[field] = {**target, "x": round(x), "y": round(y)}

        region = args.get("region")
        if isinstance(region, list) and len(region) == 4:
            x0, y0 = to_image(region[:2], space, viewport)
            x1, y1 = to_image(region[2:], space, viewport)
            converted["region"] = [round(x0), round(y0), round(x1), round(y1)]

        return converted

    # For the frontend: live frames and input during user takeover (bypasses the model, not written to the trace)
    async def screenshot(self, tab_id: str | None = None) -> bytes:
        context = await self.browser_context()
        tab = await context.tab(self.owner, tab_id)
        return await tab.page.screenshot(type="jpeg", quality=75, scale="css")

    async def watch(
        self, *, max_size: tuple[int, int] = (1280, 800), quality: int = 60, max_fps: float = 5
    ) -> AsyncIterator[BrowserFrame]:
        """Live frames following the session's current tab. Viewers of the same tab share one stream; stop iterating to stop watching."""
        context = await self.browser_context()
        async for frame in follow(
            context,
            self.owner,
            max_size=max_size,
            quality=quality,
            max_fps=max_fps,
        ):
            yield frame

    async def user_input(self, member: str, args: dict[str, Any]) -> None:
        """
        Perform an action from the user during takeover; coordinates are page CSS pixels. Doesn't check whether the action is enabled; URL rules still apply.
        The next time the model performs an action, the result mentions the user's actions.
        """
        if member not in BROWSER_USER_INPUT:
            raise ValueError(f"Unsupported user action: {member}")

        context = await self.browser_context()
        if member == "switch_tab":
            tab = await context.tab(self.owner, args["tab_id"])
            context.active[self.owner] = tab
            with contextlib.suppress(Exception):
                await tab.page.bring_to_front()
        else:
            tab = await context.tab(self.owner, args.get("tab_id"))
            if member == "type":
                await tab.page.keyboard.type(str(args["text"]))
            else:
                await context.act_on_tab(tab, member, args)

        context.note_user_input(self.owner, tab)

    async def _upload_paths(self, args: dict[str, Any]) -> tuple[list[str], bool]:
        # If the file is also visible in the workspace, it must also be readable in the sandbox, matching what the model would read with a command
        paths = [str(path) for path in args.get("paths") or []]
        if not paths:
            raise ValueError("Missing paths")
        if not self.config.node:
            raise PermissionError(strings.UPLOAD_NO_NODE)

        api = self._service.api
        node = await api.nodes.get(self.config.node, root_id=self.session_ref.root_id)
        info = await node.info()
        style = info.style
        workspace = await self._workspace()
        roots = await self._upload_roots(node, info, workspace)
        found: list[tuple[str, bool]] = []
        for path in paths:
            if not (style.is_absolute(path) or style.starts_at_home(path)):
                raise ValueError(strings.UPLOAD_NOT_ABSOLUTE.format(path=path))

            absolute = style.absolute(path, info.home)
            try:
                target = await node.stat(absolute)
            except (FileNotFoundError, NotADirectoryError):
                raise PageError(strings.UPLOAD_NOT_FOUND.format(path=path)) from None

            root = _closest_root(style, target.real_path, roots)
            if root is None:
                raise PermissionError(strings.UPLOAD_NOT_ALLOWED.format(path=path))

            entries = [(relative, real) for relative, real in await node.file_op("readable", path=target.real_path)]
            if any(_closest_root(style, real, roots) is None for _, real in entries):
                raise PermissionError(strings.UPLOAD_NOT_ALLOWED.format(path=path))

            seen_from = root[1]
            if workspace is not None and seen_from is not None:
                await _check_workspace_readable(workspace, style, path, target.real_path, root[0], seen_from, entries)

            found.append((target.real_path, target.is_dir))

        directory = any(is_dir for _, is_dir in found)
        if directory and len(found) > 1:
            raise ValueError(strings.UPLOAD_ONE_DIRECTORY)
        return [real for real, _ in found], directory

    async def _upload_roots(self, node: Any, info: Any, workspace: Any) -> list[tuple[str, str | None]]:
        style = info.style
        same_node = workspace is not None and workspace.node is node
        workspace_mounts = (
            dict(self._service.api.nodes.shared_folders(workspace.config.node)) if workspace is not None else {}
        )
        roots: list[tuple[str, str | None]] = []
        place = await self.place()
        if place.mode == "save" and place.directory is not None:
            roots.append((place.directory, place.directory if same_node else None))

        assert self.config.node is not None

        for name, mount in self._service.api.nodes.shared_folders(self.config.node):
            try:
                real = (await node.stat(style.absolute(mount, info.home))).real_path
            except OSError:
                continue

            if same_node:
                roots.append((real, real))
            elif name in workspace_mounts:
                roots.append((real, workspace.style.absolute(workspace_mounts[name], workspace.info.home)))
            else:
                roots.append((real, None))

        if same_node:
            real = (await node.stat(workspace.path)).real_path
            roots.append((real, real))

        # Files visible in the workspace must pass the sandbox check, so prefer locations that have a matching path in the workspace
        return sorted(roots, key=lambda root: root[1] is None)


def _downloads_fact(nodes: Any, browser: Browser, root_id: str) -> dict[str, Any]:
    if not browser.downloads:
        return {"mode": "deny"}
    if not browser.can_manage_downloads:
        return {"mode": "browser"}
    if browser.download_dir is not None:
        return {"mode": "save", "path": browser.download_dir}

    info = nodes.cached_info(browser.node, root_id=root_id)
    path = info.node_paths.downloads(root_id) if info is not None else None
    return {"mode": "save", "path": path, "temporary": True}


def _closest_root(style: Any, real: str, roots: list[tuple[str, str | None]]) -> tuple[str, str | None] | None:
    for root in roots:
        if style.inside(real, root[0]):
            return root
    return None


async def _check_workspace_readable(
    workspace: Any,
    style: Any,
    path: str,
    real: str,
    root: str,
    seen_from: str,
    entries: list[tuple[str, str]],
) -> None:
    relative = style.relative(real, root)
    in_workspace = (
        seen_from if relative == "." else workspace.style.join(seen_from, *relative.replace("\\", "/").split("/"))
    )
    try:
        readable = await workspace.files.list_readable(in_workspace)
    except OSError:
        raise PermissionError(strings.UPLOAD_SANDBOX.format(path=path)) from None

    def names(items: list[tuple[str, str]]) -> set[str]:
        return {item.replace("\\", "/") for item, _ in items}

    if names(readable) != names(entries):
        raise PermissionError(strings.UPLOAD_SANDBOX.format(path=path))


class BrowserService(Service):
    provides = "browser"

    async def attach(self, api: RunnerAPI) -> None:
        await super().attach(api)
        self.contexts = BrowserContexts(api.nodes, self._on_download)
        self._running_downloads: dict[tuple[str, str], collections.deque[str]] = {}

    def check(self, config: dict[str, Any]) -> None:
        browser = Browser.model_validate(config)
        if browser.node and not self.api.nodes.known(browser.node):
            raise ConfigError(f"Node {browser.node!r} referenced by the browser is not registered; register it with Runner(nodes=[...])")

    async def bind(self, session: SessionRef) -> BoundBrowser:
        return BoundBrowser(Browser.model_validate(session.resources["browser"]), session, self)

    async def facts(self, session: SessionRef) -> Any:
        """
        Return the browser information described to the model: the node the browser runs on (cdp when connected via cdp), the download directory, the directories uploads may come from (when uploads are enabled), and the description.
        Returns None when the session has no browser tools.
        """
        if "browser" not in session.tool_resources:
            return None

        browser = Browser.model_validate(session.resources["browser"])
        facts: dict[str, Any] = {"node": browser.node or "cdp"}
        directories = self._directories(session, browser)
        if directories:
            facts["directories"] = directories
        if browser.description:
            facts["description"] = browser.description

        return facts

    def _directories(self, session: SessionRef, browser: Browser) -> list[str]:
        # Matches the actual rules: downloads are saved in the _downloads_fact directory; upload locations are the same as BoundBrowser._upload_roots
        found: list[str] = []
        downloads = _downloads_fact(self.api.nodes, browser, session.root_id)
        if downloads.get("mode") == "save" and downloads.get("path"):
            found.append(downloads["path"])

        if browser.node and browser.policy.enabled("file_upload"):
            info = self.api.nodes.cached_info(browser.node, root_id=session.root_id)

            def absolute(path: str) -> str:
                return info.style.absolute(path, info.home) if info is not None else path

            found += [absolute(path) for _, path in self.api.nodes.shared_folders(browser.node)]
            workspace = session.resources.get("workspace")
            if workspace is not None and Workspace.model_validate(workspace).node == browser.node:
                found.append(absolute(Workspace.model_validate(workspace).path))

        return list(dict.fromkeys(found))

    def render(self, facts: Any) -> str:
        items: list[tuple[str, str]] = [(strings.FACTS_NODE, facts["node"])]
        if facts.get("directories"):
            items.append((strings.FACTS_DIRS, strings.FACTS_SEPARATOR.join(facts["directories"])))
        if facts.get("description"):
            items.append((strings.FACTS_DESCRIPTION, facts["description"]))

        lines = [strings.FACTS_ITEM.format(name=name, value=value) for name, value in items]
        return "\n".join([strings.FACTS_TITLE, *lines])

    async def _on_download(self, owner: str, root_id: str, change: dict[str, Any]) -> None:
        kind = change.get("type")
        url = change.get("url", "")
        key = (owner, url)
        data = {key_: value for key_, value in change.items() if key_ != "type"}
        if kind == "download_started":
            message = await self.api.add_message(
                owner, CustomMessage("browser.download", data={**data, "status": "started"}, status="in_progress")
            )
            self._running_downloads.setdefault(key, collections.deque()).append(message.id)
            return

        queue = self._running_downloads.get(key)
        message_id = queue.popleft() if queue else None

        if queue is not None and not queue:
            self._running_downloads.pop(key, None)

        if kind == "download_completed":
            if change.get("path"):
                text = strings.DOWNLOAD_COMPLETED.format(name=change.get("name"), path=change["path"])
            else:
                text = strings.DOWNLOAD_COMPLETED_BY_BROWSER.format(name=change.get("name"))
            status = "completed"
        else:
            text = strings.DOWNLOAD_FAILED.format(name=change.get("name"), error=change.get("error"))
            status = "failed"

        data["status"] = status
        if message_id is None:
            await self.api.add_message(owner, CustomMessage("browser.download", data=data, for_model=text))
        else:
            await self.api.complete_message(
                owner,
                message_id,
                status=status,
                data=data,
                for_model=text,
            )

    async def session_closing(self, session: SessionRef) -> None:
        await self.contexts.session_closing(session.id, session.root_id, session.parent_id is None)

    async def runner_stopped(self) -> None:
        if hasattr(self, "contexts"):
            await self.contexts.close()
