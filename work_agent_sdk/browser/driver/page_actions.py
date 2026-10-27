from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from typing import TYPE_CHECKING, Any

import work_agent_sdk.strings.browser as strings
from work_agent_sdk.browser.actions import modifier_keys, playwright_key, types_text
from work_agent_sdk.browser.driver.network import with_scheme
from work_agent_sdk.browser.driver.pages import (
    ACTION_TIMEOUT,
    MAX_TEXT,
    NAVIGATION_TIMEOUT,
    SCROLL_PIXELS,
    PageError,
    SensitiveInputError,
    Tab,
    with_timeout,
)
from work_agent_sdk.browser.driver.scripts import (
    FIND_SCRIPT,
    FOCUSED_SENSITIVE_SCRIPT,
    PAGE_TEXT_SCRIPT,
    READ_PAGE_SCRIPT,
)

if TYPE_CHECKING:
    from work_agent_sdk.browser.driver.contexts import BrowserContext


class PageActions:
    def __init__(self, browser: BrowserContext) -> None:
        self.browser = browser

    async def do_navigate(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        url = str(args["url"]).strip()
        page = tab.page
        if url in ("back", "forward", "reload"):
            action = {"back": page.go_back, "forward": page.go_forward, "reload": page.reload}[url]
            await with_timeout(
                action(wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT), NAVIGATION_TIMEOUT / 1000
            )
        else:
            url = with_scheme(url)

            reason = await self.browser.rules.check(url)
            if reason:
                raise PermissionError(reason)

            try:
                await with_timeout(
                    page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT),
                    NAVIGATION_TIMEOUT / 1000,
                )
            except PageError:
                raise
            except Exception as error:
                if "ERR_BLOCKED_BY_CLIENT" in str(error):
                    raise PermissionError(
                        strings.NAVIGATE_BLOCKED.format(urls=", ".join(self.browser.blocked[-3:]))
                    ) from error
                raise PageError(strings.NAVIGATE_FAILED.format(error=str(error).splitlines()[0][:300])) from None

        return {"text": strings.OPENED.format(url=page.url), "untrusted": True}

    async def do_screenshot(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        return {"image": await with_timeout(tab.page.screenshot(type="jpeg", quality=75, scale="css"), 30)}

    async def do_zoom(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        x0, y0, x1, y1 = (int(value) for value in args["region"])
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if x1 - x0 < 1 or y1 - y0 < 1:
            raise PageError(strings.ZOOM_EMPTY)

        clip = {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}
        data = await with_timeout(
            tab.page.screenshot(
                type="jpeg",
                quality=85,
                clip=clip,
                scale="device",
            ),
            30,
        )
        return {"image": data}

    async def _click(self, tab: Tab, args: dict[str, Any], button: str, count: int) -> dict[str, Any]:
        target = args["target"]
        modifiers = modifier_keys(args.get("modifiers"))
        if target.get("type") == "ref":
            handle = await self.browser.element_by_ref(tab, target["ref"])
            await with_timeout(
                handle.click(
                    button=button,
                    click_count=count,
                    modifiers=modifiers,
                    timeout=ACTION_TIMEOUT,
                )
            )
            return {"text": strings.CLICKED_REF.format(ref=target["ref"])}

        x, y = await self.browser.point(tab, target)
        keyboard = tab.page.keyboard
        for key in modifiers:
            await keyboard.down(key)

        try:
            await with_timeout(tab.page.mouse.click(x, y, button=button, click_count=count))
        finally:
            for key in reversed(modifiers):
                await keyboard.up(key)

        return {"text": strings.CLICKED_POINT}

    async def do_left_click(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        return await self._click(tab, args, "left", 1)

    async def do_right_click(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        return await self._click(tab, args, "right", 1)

    async def do_middle_click(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        return await self._click(tab, args, "middle", 1)

    async def do_double_click(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        return await self._click(tab, args, "left", 2)

    async def do_triple_click(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        return await self._click(tab, args, "left", 3)

    async def do_hover(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        x, y = await self.browser.point(tab, args["target"])
        await with_timeout(tab.page.mouse.move(x, y))
        return {"text": strings.HOVERED}

    async def do_left_click_drag(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        start = await self.browser.point(tab, args["from"])
        end = await self.browser.point(tab, args["target"])
        mouse = tab.page.mouse
        await with_timeout(mouse.move(*start))
        await with_timeout(mouse.down())
        await with_timeout(mouse.move(*end, steps=10))
        await with_timeout(mouse.up())
        return {"text": strings.DRAGGED}

    async def do_left_mouse_down(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        await with_timeout(tab.page.mouse.move(*await self.browser.point(tab, args["target"])))
        await with_timeout(tab.page.mouse.down())
        return {"text": strings.MOUSE_DOWN}

    async def do_left_mouse_up(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        await with_timeout(tab.page.mouse.move(*await self.browser.point(tab, args["target"])))
        await with_timeout(tab.page.mouse.up())
        return {"text": strings.MOUSE_UP}

    async def do_mouse_move(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        await with_timeout(tab.page.mouse.move(*await self.browser.point(tab, args["target"])))
        return {"text": strings.MOUSE_MOVED}

    async def do_scroll(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        x, y = await self.browser.point(tab, args["target"])
        amount = max(1, min(int(args.get("scroll_amount") or 3), 10)) * SCROLL_PIXELS
        direction = args["scroll_direction"]
        dx = {"left": -amount, "right": amount}.get(direction, 0)
        dy = {"up": -amount, "down": amount}.get(direction, 0)
        await with_timeout(tab.page.mouse.move(x, y))
        await with_timeout(tab.page.mouse.wheel(dx, dy))
        await asyncio.sleep(0.3)
        return {"text": strings.SCROLLED}

    async def do_scroll_to(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        handle = await self.browser.element_by_ref(tab, args["target"]["ref"])
        await with_timeout(handle.scroll_into_view_if_needed(timeout=ACTION_TIMEOUT))
        return {"text": strings.SCROLLED_TO.format(ref=args["target"]["ref"])}

    async def _check_focus(self, tab: Tab) -> None:
        if not self.browser.policy.sensitive_inputs and await with_timeout(tab.page.evaluate(FOCUSED_SENSITIVE_SCRIPT)):
            raise SensitiveInputError("focus")

    async def do_type(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        await self._check_focus(tab)
        await with_timeout(tab.page.keyboard.type(str(args["text"]), delay=10), 120)
        return {"text": strings.TYPED}

    async def do_key(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        keys = str(args["text"]).split()
        if any(types_text(key) for key in keys):
            await self._check_focus(tab)

        repeat = max(1, min(int(args.get("repeat") or 1), 100))
        for _ in range(repeat):
            for key in keys:
                await with_timeout(tab.page.keyboard.press(playwright_key(key)))

        return {"text": strings.KEY_PRESSED}

    async def do_hold_key(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        keys = [playwright_key(part) for part in str(args["text"]).split("+") if part]
        keyboard = tab.page.keyboard
        for key in keys:
            await keyboard.down(key)

        try:
            await asyncio.sleep(max(0.0, min(float(args.get("duration") or 1), 30)))
        finally:
            for key in reversed(keys):
                await keyboard.up(key)

        return {"text": strings.KEY_RELEASED}

    async def do_wait(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(max(0.0, min(float(args.get("duration") or 1), 30)))
        return {"text": strings.WAITED}

    async def do_read_page(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        root = await self.browser.element_by_ref(tab, args["ref"]) if args.get("ref") else None
        depth = max(1, int(args.get("depth") or 15))
        refs = await self.browser.current_refs(tab)
        text = await self.browser.run_page_script(
            tab, READ_PAGE_SCRIPT, root, refs, args.get("filter") or "all", depth, MAX_TEXT
        )
        title = await with_timeout(tab.page.title())
        page_text = strings.PAGE.format(title=title, url=tab.page.url, text=text or strings.PAGE_EMPTY)
        return {"text": page_text, "untrusted": True}

    async def do_find(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        refs = await self.browser.current_refs(tab)
        text = await self.browser.run_page_script(tab, FIND_SCRIPT, refs, str(args["query"]))
        return {"text": text or strings.NOT_FOUND, "untrusted": True}

    async def do_get_page_text(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        text = await with_timeout(tab.page.evaluate(PAGE_TEXT_SCRIPT, MAX_TEXT))
        return {"text": text or strings.NO_TEXT, "untrusted": True}

    async def do_form_input(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        handle = await self.browser.element_by_ref(tab, args["target"]["ref"])
        if not self.browser.policy.sensitive_inputs and await self.browser.is_sensitive(handle):
            raise SensitiveInputError("field")

        value = args["value"]
        kind = await with_timeout(handle.evaluate("element => [element.tagName, (element.type || '').toLowerCase()]"))
        if kind[0] == "SELECT":
            try:
                await with_timeout(handle.select_option(label=str(value), timeout=ACTION_TIMEOUT))
            except Exception:
                await with_timeout(handle.select_option(str(value), timeout=ACTION_TIMEOUT))
        elif kind[1] in ("checkbox", "radio"):
            await with_timeout(handle.set_checked(bool(value), timeout=ACTION_TIMEOUT))
        else:
            await with_timeout(handle.fill(str(value), timeout=ACTION_TIMEOUT))

        return {"text": strings.FIELD_SET.format(ref=args["target"]["ref"])}

    async def do_file_upload(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        handle = await self.browser.element_by_ref(tab, args["target"]["ref"])
        paths: list[str] = args["_paths"]
        kind = await with_timeout(
            handle.evaluate("element => [element.tagName, element.type, element.multiple, element.webkitdirectory]")
        )
        if kind[0] != "INPUT" or str(kind[1]).lower() != "file":
            raise PageError(f"{args['target']['ref']} is not a file upload input")
        if args.get("_directory") and not kind[3]:
            raise PageError(strings.UPLOAD_NO_DIRECTORY)
        if len(paths) > 1 and not kind[2]:
            raise PageError(strings.UPLOAD_SINGLE)

        await with_timeout(set_input_paths(tab.page, handle, paths), 60)
        return {"text": strings.UPLOADED.format(count=len(paths))}

    async def do_read_console(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        return {"text": "\n".join(tab.console) or strings.NO_CONSOLE, "untrusted": True}

    async def do_read_network(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        return {"text": "\n".join(tab.network) or strings.NO_NETWORK, "untrusted": True}

    async def do_javascript_exec(self, tab: Tab, args: dict[str, Any]) -> dict[str, Any]:
        code = str(args["text"])
        script = f"async () => {{ return await (async () => {{ {code}\n }})(); }}"
        try:
            value = await with_timeout(tab.page.evaluate(script))
        except PageError:
            raise
        except Exception as error:
            try:
                value = await with_timeout(tab.page.evaluate(code))
            except Exception:
                raise PageError(strings.SCRIPT_FAILED.format(error=str(error).splitlines()[0][:300])) from None

        text = json.dumps(value, ensure_ascii=False, default=str)
        return {"text": text[:MAX_TEXT], "untrusted": True}

    async def do_new_tab(self, owner: str, args: dict[str, Any]) -> dict[str, Any]:
        tab = await self.browser.new_tab(owner)
        self.browser.active[owner] = tab
        return {"text": strings.TAB_OPENED.format(tab=tab.id)}

    async def do_list_tabs(self, owner: str, args: dict[str, Any]) -> dict[str, Any]:
        state = await self.browser.with_titles(self.browser.state(owner))
        lines = [
            f"{tab['tab_id']}{' *' if tab.get('active') else ''}{' ' + tab['title'] if tab['title'] else ''} — {tab['url']}"
            for tab in state["tabs"]
        ]

        if state.get("state_changes"):
            self.browser.changes[owner] = state["state_changes"] + self.browser.changes.get(owner, [])

        return {"text": "\n".join(lines) or strings.NO_TABS, "untrusted": True}

    async def do_switch_tab(self, owner: str, args: dict[str, Any]) -> dict[str, Any]:
        tab = await self.browser.tab(owner, args["tab_id"])
        self.browser.active[owner] = tab

        with contextlib.suppress(Exception):
            await tab.page.bring_to_front()

        return {"text": strings.TAB_SWITCHED.format(tab=tab.id)}

    async def do_close_tab(self, owner: str, args: dict[str, Any]) -> dict[str, Any]:
        tab = await self.browser.tab(owner, args["tab_id"])
        await tab.page.close()
        self.browser.drop_tab(tab.page)
        return {"text": strings.TAB_CLOSED.format(tab=tab.id)}


async def set_input_paths(page: Any, handle: Any, paths: list[str]) -> None:
    token = uuid.uuid4().hex
    await handle.evaluate("(element, token) => element.setAttribute('data-work-agent-upload', token)", token)
    from playwright.async_api import Error as PlaywrightError

    frame = await handle.owner_frame()
    try:
        # Out-of-process iframes have their own CDP session; everything else is in the page's session
        session = await page.context.new_cdp_session(frame)
    except PlaywrightError:
        session = await page.context.new_cdp_session(page)

    try:
        await session.send("DOM.getDocument", {"depth": -1, "pierce": True})
        search = await session.send("DOM.performSearch", {"query": f'[data-work-agent-upload="{token}"]'})
        try:
            count = search["resultCount"]
            nodes = (
                await session.send(
                    "DOM.getSearchResults", {"searchId": search["searchId"], "fromIndex": 0, "toIndex": count}
                )
                if count
                else {"nodeIds": []}
            )
        finally:
            await session.send("DOM.discardSearchResults", {"searchId": search["searchId"]})

        if len(nodes["nodeIds"]) != 1:
            raise PageError("Couldn't locate the upload input (the page may have changed); run read_page or find again")

        await session.send("DOM.setFileInputFiles", {"files": paths, "nodeId": nodes["nodeIds"][0]})
    finally:
        with contextlib.suppress(Exception):
            await handle.evaluate("element => element.removeAttribute('data-work-agent-upload')")
        with contextlib.suppress(Exception):
            await session.detach()
