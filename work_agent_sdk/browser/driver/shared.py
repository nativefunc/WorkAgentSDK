from __future__ import annotations

import asyncio
import collections
import contextlib
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from work_agent_sdk.browser.driver.downloads import safe_file_name
from work_agent_sdk.browser.driver.pages import (
    redact_url_secrets,
)
from work_agent_sdk.core.utils import new_id

if TYPE_CHECKING:
    from work_agent_sdk.browser.driver.connections import BrowserContexts
    from work_agent_sdk.browser.driver.contexts import BrowserContext


class SharedContext:
    # 网址规则和下载目录按上下文设置：请求按来源标签页所属的会话树分派，来源不明的按最严格的规则处理

    def __init__(self, manager: BrowserContexts, context: Any, browser: Any, *, owned: bool) -> None:
        self.manager = manager
        self.context = context
        self.browser = browser
        self.owned = owned
        self.trees: list[BrowserContext] = []

        # 下载：浏览器先在其所在节点上保存到暂存目录（文件名为随机 id），完成后由对应会话树改名并移入自己的目录
        self.id: str | None = None
        self.cdp: Any = None
        self.staging_node: Any = None
        self.staging_style: Any = None
        self.staging: str | None = None
        self.behavior: str | None = None
        self._names: dict[str, tuple[str, str]] = {}

        # Playwright 的下载事件包含标签页，CDP 的事件包含文件，二者仅网址相同：同一网址并发下载时按先后顺序匹配
        self._owners: dict[str, collections.deque[tuple[BrowserContext, str]]] = {}
        self.finishing: set[asyncio.Task] = set()

    async def start(self, first_page: Any = None) -> None:
        await self.context.route("**/*", self._route)
        await self.context.route_web_socket("**/*", self._websocket)

        if first_page is not None:
            # 设置下载需要该上下文在浏览器中的 id，只能通过页面查询
            inspector = await self.context.new_cdp_session(first_page)
            info = await inspector.send("Target.getTargetInfo")
            self.id = info["targetInfo"].get("browserContextId")

            with contextlib.suppress(Exception):
                await inspector.detach()

        self.cdp = await self.browser.new_browser_cdp_session()
        self.cdp.on("Browser.downloadWillBegin", self._download_begin)
        self.cdp.on("Browser.downloadProgress", self._download_progress)

    async def attach(self, tree: BrowserContext) -> None:
        self.trees.append(tree)
        await self._apply_downloads()

    async def detach(self, tree: BrowserContext) -> bool:
        if tree in self.trees:
            self.trees.remove(tree)

        if self.trees:
            await self._apply_downloads()
            return False

        for task in self.finishing:
            task.cancel()

        with contextlib.suppress(Exception):
            if self.owned:
                await self.context.close()
            else:
                await self.context.unroute("**/*", self._route)

        with contextlib.suppress(Exception):
            await self.cdp.detach()

        if self.staging is not None:
            with contextlib.suppress(Exception):
                await self.staging_node.remove(self.staging)

        return True

    def owner(self, page: Any) -> BrowserContext | None:
        for tree in self.trees:
            if page in tree.pages:
                return tree
        return None

    async def _trees_for(self, page: Any) -> list[BrowserContext]:
        tree = self.owner(page) if page is not None else None
        if tree is None and page is not None:
            with contextlib.suppress(Exception):
                tree = self.owner(await page.opener())

        return [tree] if tree is not None else list(self.trees)

    async def _blocked_by(self, url: str, trees: list[BrowserContext]) -> bool:
        blocked = False
        for tree in trees:
            if await tree.rules.check(url):
                tree.blocked.append(url)
                blocked = True
        return blocked

    async def _route(self, route: Any) -> None:
        page = None
        with contextlib.suppress(Exception):
            page = route.request.frame.page
        if await self._blocked_by(route.request.url, await self._trees_for(page)):
            await route.abort("blockedbyclient")
        else:
            await route.continue_()

    async def _websocket(self, websocket: Any) -> None:
        # Playwright 不提供 WebSocket 的来源页面
        if await self._blocked_by(websocket.url, list(self.trees)):
            await websocket.close()
        else:
            websocket.connect_to_server()

    async def _apply_downloads(self) -> None:
        modes = {tree.place.mode for tree in self.trees}
        if "save" in modes:
            behavior = "allowAndName"
        elif modes == {"deny"}:
            behavior = "deny"
        else:
            return
        if behavior == self.behavior:
            return

        params: dict[str, Any] = {"behavior": behavior, "eventsEnabled": True}

        if behavior == "allowAndName" and self.staging is None:
            tree = next(tree for tree in self.trees if tree.place.mode == "save")
            self.staging_node = tree.place.node
            info = await self.staging_node.info()
            self.staging_style = info.style
            self.staging = info.node_paths.incoming(new_id("ctx_"))
            await self.staging_node.make_dir(self.staging)

        if behavior == "allowAndName":
            params["downloadPath"] = self.staging
        if self.id:
            params["browserContextId"] = self.id

        await self.cdp.send("Browser.setDownloadBehavior", params)
        self.behavior = behavior

    def remember_download(self, url: str, tree: BrowserContext, owner: str) -> None:
        self._owners.setdefault(url, collections.deque()).append((tree, owner))

    def forget(self, url: str, tree: BrowserContext, owner: str) -> None:
        owners = self._owners.get(url)
        if owners and (tree, owner) in owners:
            owners.remove((tree, owner))
            if not owners:
                del self._owners[url]

    def _pop_download_owner(self, url: str) -> tuple[BrowserContext, str] | None:
        owners = self._owners.get(url)
        if not owners:
            return None

        found = owners.popleft()

        if not owners:
            del self._owners[url]

        return found

    def _download_begin(self, event: dict[str, Any]) -> None:
        self._names[event["guid"]] = (event.get("suggestedFilename") or "", event.get("url") or "")

    def _download_progress(self, event: dict[str, Any]) -> None:
        if event.get("state") == "canceled":
            self._names.pop(event.get("guid", ""), None)
        if event.get("state") != "completed" or self.staging is None:
            return

        task = asyncio.ensure_future(self._finish(event["guid"]))
        self.finishing.add(task)
        task.add_done_callback(self.finishing.discard)

    async def _finish(self, guid: str) -> None:
        # 暂存目录中找不到的文件属于同一浏览器的其他上下文
        source = self.staging_style.join(self.staging, guid)
        try:
            info = await self.staging_node.stat(source)
        except FileNotFoundError:
            return

        name, url = self._names.pop(guid, ("", ""))
        name = safe_file_name(name or urlsplit(url).path.rsplit("/", 1)[-1])  # 网址中的路径始终以 / 分隔
        url = redact_url_secrets(url)[:4096]
        found = self._pop_download_owner(url)
        if found is None and self.trees:
            found = (self.trees[0], self.trees[0].root_id)

        if found is None:
            await self.staging_node.remove(source)
            return

        tree, owner = found
        await tree.place_download(source, info.size, name, url, owner)
