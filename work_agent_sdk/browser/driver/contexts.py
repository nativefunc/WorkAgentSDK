from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from work_agent_sdk.browser.actions import BROWSER
from work_agent_sdk.browser.config import Browser
from work_agent_sdk.browser.driver.downloads import (
    DownloadPlace,
    numbered_name,
    safe_file_name,
)
from work_agent_sdk.browser.driver.network import url_rules
from work_agent_sdk.browser.driver.page_actions import PageActions
from work_agent_sdk.browser.driver.pages import (
    ACTION_TIMEOUT,
    DOWNLOAD_WAIT,
    PageError,
    Tab,
    redact_url_secrets,
    with_timeout,
)
from work_agent_sdk.browser.driver.scripts import (
    DESCRIBE_SCRIPT,
    ELEMENT_AT_SCRIPT,
    SENSITIVE_INPUT_SCRIPT,
)
from work_agent_sdk.browser.driver.shared import SharedContext

if TYPE_CHECKING:
    from work_agent_sdk.browser.driver.connections import BrowserContexts

logger = logging.getLogger("work_agent_sdk")

MAX_REFS = 5000


class BrowserContext:
    def __init__(self, manager: BrowserContexts, root_id: str, config: Browser, place: DownloadPlace) -> None:
        self.manager = manager
        self.root_id = root_id
        self.config = config
        self.policy = config.policy
        self.actions = PageActions(self)
        self.rules = url_rules(config.policy)
        self.shared: SharedContext | None = None
        self.context: Any = None
        self.tabs: dict[str, Tab] = {}
        self._by_page: dict[Any, Tab] = {}
        self._next_tab = 1

        # Each session's current tab, plus changes not yet reported (e.g. a new tab popped up)
        self.active: dict[str, Tab] = {}
        self.blocked: list[str] = []
        self.changes: dict[str, list[dict[str, Any]]] = {}
        # Sessions not yet told that the browser connection dropped and was re-established: their previous tab ids are no longer valid
        self.reconnected: set[str] = set()
        # Sessions that have used this browser: on disconnect pages fire close first, so after reconnecting there's no way to tell whose tabs became invalid
        self._owners: set[str] = set()

        # Tabs currently streaming frames (see live.py), keyed by tab id
        self.screencasts: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self.place = place
        self._downloading: set[asyncio.Task] = set()

        # Background tasks triggered by page events (adopting new pages, recording requests, stopping streams); cancelled together on close
        self._tasks: set[asyncio.Task[Any]] = set()
        self._naming = asyncio.Lock()

    async def ensure(self) -> None:
        async with self._lock:
            host = await self.manager.host(self.config, self.root_id)
            if self.shared is not None and self.shared.browser is host.browser:
                return

            if self.shared is not None:
                self.reconnected.update(self._owners)
            self.tabs.clear()
            self._by_page.clear()
            self.active.clear()

            if self.config.profile == "session":
                width, height = self.config.viewport
                context = await host.browser.new_context(viewport={"width": width, "height": height})
                self.shared = SharedContext(self.manager, context, host.browser, owned=True)
                self.context = context

                first = await self.new_tab(self.root_id)
                self.active[self.root_id] = first
                await self.shared.start(first.page)
            else:
                if host.shared is None:
                    contexts = host.browser.contexts
                    context = contexts[0] if contexts else await host.browser.new_context()
                    host.shared = SharedContext(self.manager, context, host.browser, owned=False)
                    await host.shared.start()
                self.shared = host.shared
                self.context = self.shared.context

            self.context.on("page", self._on_page)

            if self.config.profile == "shared":
                # The user's own browser: already-open tabs belong to the main agent
                for page in self.context.pages:
                    self._adopt(page, self.root_id)

            await self.shared.attach(self)

    @property
    def pages(self) -> dict[Any, Tab]:
        return self._by_page

    def _report(self, owner: str, change: dict[str, Any]) -> None:
        self.changes.setdefault(owner, []).append(change)

    async def _report_download(self, owner: str, change: dict[str, Any]) -> None:
        with contextlib.suppress(Exception):
            await self.manager.on_download(owner, self.root_id, change)

    def _on_page(self, page: Any) -> None:
        self._spawn(self._adopt_new_page(page))

    def _spawn(self, work: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.ensure_future(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _adopt_new_page(self, page: Any) -> None:
        opener = None
        with contextlib.suppress(Exception):
            opener = self._by_page.get(await page.opener())

        if page in self._by_page:
            return

        if opener is not None:
            self._adopt(page, opener.owner, opened=True)
        elif self.config.profile == "shared" or (self.shared is not None and self.shared.owned):
            self._adopt(page, self.root_id, opened=True)

    async def new_tab(self, owner: str) -> Tab:
        # The new-page event may arrive first and be misattributed to someone else; the actual opener wins
        page = await self.context.new_page()
        tab = self._adopt(page, owner)
        if tab.owner != owner:
            reported = self.changes.get(tab.owner, [])
            self.changes[tab.owner] = [change for change in reported if change.get("tab_id") != tab.id]
            if self.active.get(tab.owner) is tab:
                self.active.pop(tab.owner)

            tab.owner = owner

        return tab

    def _adopt(self, page: Any, owner: str, opened: bool = False) -> Tab:
        tab = self._by_page.get(page)
        if tab is not None:
            return tab

        tab = Tab(f"tab-{self._next_tab}", page, owner)
        self._owners.add(owner)
        self._next_tab += 1
        self.tabs[tab.id] = tab
        self._by_page[page] = tab
        page.on(
            "console", lambda message: tab.console.append(redact_url_secrets(f"[{message.type}] {message.text}")[:500])
        )
        page.on("requestfinished", lambda request: self._log_request(tab, request))
        page.on(
            "requestfailed",
            lambda request: tab.network.append(redact_url_secrets(f"{request.method} {request.url} failed")[:500]),
        )
        page.on("download", self._on_download)
        page.on("close", lambda _: self.drop_tab(page))

        if opened:
            self._report(owner, {"type": "tab_opened", "tab_id": tab.id})

        return tab

    def _log_request(self, tab: Tab, request: Any) -> None:
        async def record() -> None:
            with contextlib.suppress(Exception):
                response = await request.response()
                status = response.status if response else "-"
                tab.network.append(redact_url_secrets(f"{request.method} {request.url} {status}")[:500])

        self._spawn(record())

    def drop_tab(self, page: Any) -> None:
        tab = self._by_page.pop(page, None)
        if tab is not None:
            self.tabs.pop(tab.id, None)
            cast = self.screencasts.pop(tab.id, None)
            if cast is not None:
                self._spawn(cast.stop())
            if self.active.get(tab.owner) is tab:
                self.active.pop(tab.owner)

    def _own_tabs(self, owner: str) -> list[Tab]:
        return [tab for tab in self.tabs.values() if tab.owner == owner and not tab.page.is_closed()]

    async def viewport(self, owner: str, tab_id: str | None = None) -> tuple[int, int]:
        page = (await self.tab(owner, tab_id)).page
        size = page.viewport_size
        if size is None:
            # When connecting to an existing browser the page has no fixed viewport; use the window's current size
            size = await with_timeout(page.evaluate("({width: innerWidth, height: innerHeight})"))

        return int(size["width"]), int(size["height"])

    async def tab(self, owner: str, tab_id: str | None = None) -> Tab:
        if tab_id:
            tab = self.tabs.get(tab_id)
            if tab is None or tab.owner != owner:
                raise PageError(f"Tab {tab_id} does not exist")
            return tab

        active = self.active.get(owner)
        if active is None or active.page.is_closed():
            own = self._own_tabs(owner)
            active = own[-1] if own else await self.new_tab(owner)
            self.active[owner] = active

        return active

    def take_reconnected(self, owner: str) -> bool:
        if owner not in self.reconnected:
            return False
        self.reconnected.discard(owner)
        return True

    def note_user_input(self, owner: str, tab: Tab) -> None:
        pending = self.changes.get(owner) or []
        if pending and pending[-1] == {"type": "user_input", "tab_id": tab.id}:
            return

        self._report(owner, {"type": "user_input", "tab_id": tab.id})

    def state(self, owner: str) -> dict[str, Any]:
        tabs = []
        for tab in self._own_tabs(owner):
            entry: dict[str, Any] = {"tab_id": tab.id, "title": "", "url": tab.page.url[:4096]}
            if tab is self.active.get(owner):
                entry["active"] = True
            tabs.append(entry)

        state: dict[str, Any] = {"tabs": tabs}
        changes = self.changes.pop(owner, [])
        if changes:
            state["state_changes"] = changes[:200]

        return state

    async def forget_owner(self, owner: str) -> None:
        for tab in self._own_tabs(owner):
            with contextlib.suppress(Exception):
                await tab.page.close()

        self.active.pop(owner, None)
        self.changes.pop(owner, None)
        self._owners.discard(owner)
        self.reconnected.discard(owner)

    async def with_titles(self, state: dict[str, Any]) -> dict[str, Any]:
        for entry in state["tabs"]:
            tab = self.tabs.get(entry["tab_id"])
            if tab is not None:
                with contextlib.suppress(Exception):
                    entry["title"] = (await with_timeout(tab.page.title(), 5))[:4096]
        return state

    async def close(self) -> None:
        for task in [*self._downloading, *self._tasks]:
            task.cancel()

        if self.shared is not None:
            with contextlib.suppress(Exception):
                self.context.remove_listener("page", self._on_page)
                if not self.shared.owned and self.config.profile != "shared":
                    for tab in list(self.tabs.values()):
                        if not tab.page.is_closed():
                            await tab.page.close()
            if await self.shared.detach(self):
                self.manager.forget_shared(self.shared)

        self.shared = None
        self.context = None

        # Delete the framework's default download directory (a download_dir specified by the developer is kept)
        place = self.place
        if place.mode == "save" and place.temporary:
            with contextlib.suppress(Exception):
                await place.node.remove(place.directory)

    async def element_by_ref(self, tab: Tab, ref: str) -> Any:
        match = re.fullmatch(r"ref_(\d+)", str(ref).strip())
        handle = None
        if match and 0 < int(match.group(1)) <= len(tab.refs):
            handle = tab.refs[int(match.group(1)) - 1]

        connected = False
        if handle is not None:
            with contextlib.suppress(Exception):
                connected = await with_timeout(handle.evaluate("element => element.isConnected"))

        if not connected:
            raise PageError(f"{ref} does not exist on the page (the page may have changed); run read_page or find again")
        return handle

    async def current_refs(self, tab: Tab) -> list[Any]:
        if tab.refs:
            try:
                await with_timeout(tab.refs[0].evaluate("element => element.isConnected"))
            except PageError:
                raise
            except Exception:
                # The page has switched to a new document; all elements from the old document are invalid
                tab.refs = []

        # Can only be cleared before running the script: the script continues numbering from the existing count
        if len(tab.refs) > MAX_REFS:
            tab.refs = []

        return tab.refs

    async def run_page_script(self, tab: Tab, script: str, *arguments: Any) -> str:
        result = await with_timeout(tab.page.evaluate_handle(script, [*arguments]))
        try:
            text = await with_timeout((await result.get_property("text")).json_value())
            fresh = await with_timeout((await result.get_property("fresh")).get_properties())
        finally:
            with contextlib.suppress(Exception):
                await result.dispose()

        indexes = sorted((index for index in fresh if index.isdigit()), key=int)
        tab.refs.extend(fresh[index].as_element() for index in indexes)
        return text

    async def point(self, tab: Tab, target: dict[str, Any]) -> tuple[float, float]:
        if target.get("type") == "ref":
            handle = await self.element_by_ref(tab, target["ref"])
            await with_timeout(handle.scroll_into_view_if_needed(timeout=ACTION_TIMEOUT))
            box = await with_timeout(handle.bounding_box())
            if box is None:
                raise PageError(f"{target['ref']} is not currently visible")
            return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

        return float(target["x"]), float(target["y"])

    async def describe(self, tab: Tab, target: dict[str, Any] | None) -> dict[str, Any]:
        page = tab.page
        description: dict[str, Any] = {"page": {"url": page.url}, "element": None}
        handle = None
        if target and target.get("type") == "ref":
            handle = await self.element_by_ref(tab, target["ref"])
        elif target:
            handle = (
                await with_timeout(page.evaluate_handle(ELEMENT_AT_SCRIPT, [target["x"], target["y"]]))
            ).as_element()
        else:
            handle = (await with_timeout(page.evaluate_handle("document.activeElement"))).as_element()

        if handle is not None:
            description["element"] = await with_timeout(handle.evaluate(DESCRIBE_SCRIPT))

        return description

    async def is_sensitive(self, handle: Any) -> bool:
        return bool(await with_timeout(handle.evaluate(SENSITIVE_INPUT_SCRIPT)))

    # Downloads: the browser first saves the file to the context's staging directory (SharedContext), then hands it over here on completion; restore the original file name and move it into this session tree's directory
    async def place_download(self, source: str, size: int, name: str, url: str, owner: str) -> None:
        place = self.place
        node = place.node
        if place.mode != "save" or place.style is None or place.directory is None:
            # A download in a shared context started by this session tree, but this session tree doesn't accept downloads
            with contextlib.suppress(Exception):
                await node.remove(source)
            await self._report_download(
                owner, {"type": "download_failed", "name": name, "url": url, "error": "This browser doesn't accept downloads"}
            )
            return

        try:
            async with self._naming:
                existing = {item.name for item in await node.list_dir(place.directory)}
                for index in range(1, 1000):
                    candidate = name if index == 1 else numbered_name(name, index - 1)
                    if candidate in existing:
                        continue

                    target = place.style.join(place.directory, candidate)
                    try:
                        await node.move(source, target)
                        break
                    except FileExistsError:
                        existing.add(candidate)
                else:
                    raise RuntimeError("Too many files with the same name; couldn't generate a usable file name")
        except Exception as error:
            logger.warning("Failed to save downloaded file: %s", error)
            await self._report_download(
                owner,
                {
                    "type": "download_failed",
                    "name": name,
                    "url": url,
                    "error": str(error)[:300],
                },
            )
            return

        await self._report_download(
            owner,
            {
                "type": "download_completed",
                "name": candidate,
                "url": url,
                "size_bytes": size,
                "path": target,
            },
        )

    def _on_download(self, download: Any) -> None:
        name = safe_file_name(download.suggested_filename)
        url = redact_url_secrets(download.url)[:4096]
        tab = self._by_page.get(download.page)
        owner = tab.owner if tab is not None else self.root_id
        if self.place.mode == "save" and self.shared is not None:
            # After the download completes, the context hands it back via a CDP event, and the initiator is found again by URL
            self.shared.remember_download(url, self, owner)

        task = asyncio.ensure_future(self._watch_download(download, owner, name, url))
        self._downloading.add(task)
        task.add_done_callback(self._downloading.discard)

    async def _watch_download(self, download: Any, owner: str, name: str, url: str) -> None:
        await self._report_download(owner, {"type": "download_started", "name": name, "url": url})
        failure = await download.failure()
        if failure:
            if self.shared is not None:
                self.shared.forget(url, self, owner)
            reason = "This browser doesn't accept downloads" if self.place.mode == "deny" else f"Download did not complete: {failure}"
            await self._report_download(
                owner,
                {
                    "type": "download_failed",
                    "name": name,
                    "url": url,
                    "error": reason,
                },
            )
        elif self.place.mode == "browser":
            await self._report_download(
                owner,
                {
                    "type": "download_completed",
                    "name": name,
                    "url": url,
                    "path": None,
                },
            )

    async def wait_loaded(self, tab: Tab) -> None:
        with contextlib.suppress(Exception):
            await tab.page.wait_for_load_state("domcontentloaded", timeout=ACTION_TIMEOUT)

    async def wait_settled(self, tab: Tab) -> None:
        await self.wait_loaded(tab)
        await asyncio.sleep(0.2)

        if self._downloading:
            await asyncio.wait(self._downloading, timeout=DOWNLOAD_WAIT)
        if self.shared is not None and self.shared.finishing:
            await asyncio.wait(self.shared.finishing, timeout=DOWNLOAD_WAIT)

    def take_blocked(self) -> list[str]:
        blocked, self.blocked = self.blocked, []
        return blocked

    # Actions: return {"text": text for the model, "untrusted": whether the text comes from the web page, "image": screenshot}
    async def perform(self, owner: str, member: str, args: dict[str, Any]) -> dict[str, Any]:
        action = BROWSER.get(member)
        if action is None:
            raise PageError(f"Unsupported action: {member}")

        handler = HANDLERS[member]
        if action.tabs:
            return await handler(self.actions, owner, args)

        tab = await self.tab(owner, args.get("tab_id"))
        if action.reads_page:
            await self.wait_loaded(tab)
        result = await handler(self.actions, tab, args)

        if action.settles:
            await self.wait_settled(tab)

        return result

    async def act_on_tab(self, tab: Tab, member: str, args: dict[str, Any]) -> dict[str, Any]:
        action = BROWSER.get(member)
        if action is None or action.tabs:
            raise PageError(f"Unsupported action: {member}")
        return await HANDLERS[member](self.actions, tab, args)

    async def targets(self, owner: str, member: str, args: dict[str, Any]) -> dict[str, Any]:
        tab = await self.tab(owner, args.get("tab_id"))
        target = args.get("target")

        if member == "navigate":
            return {
                "page": {"url": tab.page.url},
                "element": None,
                "url": args.get("url"),
                "submits": False,
            }

        description = await self.describe(tab, target if isinstance(target, dict) else None)
        element = description["element"] or {}
        submits = False
        url = None
        if member.endswith("click"):
            submits = bool(element.get("submits"))
            url = element.get("href")

        if member == "key" and "enter" in str(args.get("text", "")).lower():
            submits = bool(element.get("form"))
        if submits and element.get("form"):
            url = element["form"].get("action")

        return {
            **description,
            "url": url,
            "submits": submits,
            "host": urlsplit(url or tab.page.url).hostname,
        }


# Action name -> handler, one-to-one with BROWSER in browser/actions.py
HANDLERS: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    "navigate": PageActions.do_navigate,
    "screenshot": PageActions.do_screenshot,
    "zoom": PageActions.do_zoom,
    "left_click": PageActions.do_left_click,
    "right_click": PageActions.do_right_click,
    "middle_click": PageActions.do_middle_click,
    "double_click": PageActions.do_double_click,
    "triple_click": PageActions.do_triple_click,
    "hover": PageActions.do_hover,
    "left_click_drag": PageActions.do_left_click_drag,
    "left_mouse_down": PageActions.do_left_mouse_down,
    "left_mouse_up": PageActions.do_left_mouse_up,
    "mouse_move": PageActions.do_mouse_move,
    "scroll": PageActions.do_scroll,
    "scroll_to": PageActions.do_scroll_to,
    "type": PageActions.do_type,
    "key": PageActions.do_key,
    "hold_key": PageActions.do_hold_key,
    "wait": PageActions.do_wait,
    "read_page": PageActions.do_read_page,
    "find": PageActions.do_find,
    "get_page_text": PageActions.do_get_page_text,
    "form_input": PageActions.do_form_input,
    "file_upload": PageActions.do_file_upload,
    "read_console": PageActions.do_read_console,
    "read_network": PageActions.do_read_network,
    "javascript_exec": PageActions.do_javascript_exec,
    "new_tab": PageActions.do_new_tab,
    "list_tabs": PageActions.do_list_tabs,
    "switch_tab": PageActions.do_switch_tab,
    "close_tab": PageActions.do_close_tab,
}
if set(HANDLERS) != set(BROWSER.names):
    raise RuntimeError(f"Browser action table doesn't match the handlers: {sorted(set(HANDLERS) ^ set(BROWSER.names))}")
