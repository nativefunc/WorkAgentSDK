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


class BoundBrowser:
    """绑定到某个会话的浏览器，即 ctx.browser 与 await session.browser() 返回的对象。"""

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
        """标签页可见区域的尺寸（CSS 像素），即模型截图的尺寸；省略 tab_id 时为当前标签页。"""
        return await (await self.browser_context()).viewport(self.owner, tab_id)

    async def perform(self, member: str, args: dict[str, Any]) -> dict[str, Any]:
        """执行一个动作，参数与模型的工具相同。启用和确认由工具负责，这里只检查网址规则，违反时抛出 PermissionError。"""
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
        供钩子使用：返回本次动作实际作用的目标（页面网址、元素、链接或表单提交地址、是否提交）。
        参数为 before_tool 收到的调用，或 (成员名, 参数)。
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

    # 供前端使用：用户接管时的实时画面和输入（不经过模型，不写入 trace）
    async def screenshot(self, tab_id: str | None = None) -> bytes:
        context = await self.browser_context()
        tab = await context.tab(self.owner, tab_id)
        return await tab.page.screenshot(type="jpeg", quality=75, scale="css")

    async def watch(
        self, *, max_size: tuple[int, int] = (1280, 800), quality: int = 60, max_fps: float = 5
    ) -> AsyncIterator[BrowserFrame]:
        """实时画面，跟随该会话的当前标签页。同一标签页的观看者共用一路画面，停止迭代即结束观看。"""
        context = await self.browser_context()
        async for frame in follow(context, self.owner, max_size=max_size, quality=quality, max_fps=max_fps):
            yield frame

    async def user_input(self, member: str, args: dict[str, Any]) -> None:
        """
        执行用户接管时的操作，坐标为页面 CSS 像素。不受面向模型的限制，但网址规则仍然生效；
        模型的下一次动作结果中会告知用户的操作。
        """
        if member not in BROWSER_USER_INPUT:
            raise ValueError(f"不支持的用户操作：{member}")

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
        # 文件在工作区中也可见时，还须在沙箱中可读，与模型用命令读到的一致
        paths = [str(path) for path in args.get("paths") or []]
        if not paths:
            raise ValueError("缺少 paths")
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

        # 文件在工作区中可见时须经过沙箱检查，因此优先匹配工作区中有对应路径的位置
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
            raise ConfigError(f"浏览器引用的节点 {browser.node!r} 未登记；请通过 Runner(nodes=[...]) 登记该节点")

    async def bind(self, session: SessionRef) -> BoundBrowser:
        return BoundBrowser(Browser.model_validate(session.resources["browser"]), session, self)

    async def facts(self, session: SessionRef) -> Any:
        browser = Browser.model_validate(session.resources["browser"])
        facts: dict[str, Any] = {
            "node": browser.node,
            "cdp": bool(browser.cdp),
            "own_browser": browser.profile == "shared",
            "downloads": _downloads_fact(self.api.nodes, browser, session.root_id),
        }
        if browser.node:
            facts["online"] = self.api.nodes.online(browser.node, root_id=session.root_id)
            facts["shared_folders"] = self.api.nodes.shared_folders(browser.node)

        if browser.description:
            facts["description"] = browser.description

        return facts

    def render(self, facts: Any) -> str:
        first = strings.FACTS_ON_NODE.format(node=facts["node"]) if facts.get("node") else strings.FACTS_EXTERNAL
        if facts.get("own_browser"):
            first += strings.FACTS_OWN_BROWSER

        lines = [first + "。"]
        downloads = facts.get("downloads") or {}
        if downloads.get("mode") == "deny":
            lines.append(strings.FACTS_DOWNLOADS_DENIED)
        elif downloads.get("mode") == "browser":
            lines.append(strings.FACTS_DOWNLOADS_BY_BROWSER)
        elif downloads.get("mode") == "save":
            if not downloads.get("path"):
                lines.append(strings.FACTS_DOWNLOAD_DIR_DEFAULT)
            elif downloads.get("temporary"):
                lines.append(strings.FACTS_DOWNLOAD_DIR_TEMPORARY.format(path=downloads["path"]))
            else:
                lines.append(strings.FACTS_DOWNLOAD_DIR.format(path=downloads["path"]))

        for name, path in facts.get("shared_folders") or []:
            lines.append(strings.FACTS_SHARED_FOLDER.format(name=name, path=path))

        if facts.get("online") is False:
            lines.append(strings.FACTS_OFFLINE)
        if facts.get("description"):
            lines.append(strings.FACTS_DESCRIPTION.format(description=facts["description"]))

        return "\n".join(lines)

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
            await self.api.complete_message(owner, message_id, status=status, data=data, for_model=text)

    async def session_closing(self, session: SessionRef) -> None:
        await self.contexts.session_closing(session.id, session.root_id, session.parent_id is None)

    async def runner_stopped(self) -> None:
        if hasattr(self, "contexts"):
            await self.contexts.close()
