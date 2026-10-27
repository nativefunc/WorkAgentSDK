from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from work_agent_sdk.browser.config import Browser
from work_agent_sdk.browser.driver.contexts import BrowserContext
from work_agent_sdk.browser.driver.downloads import DownloadPlace
from work_agent_sdk.browser.driver.shared import SharedContext
from work_agent_sdk.core.utils import expand_env, has_env_reference
from work_agent_sdk.host.browser import BrowserOptions
from work_agent_sdk.nodes.base import PortForward

CONNECT_RETRY_DELAYS = (0.5, 1.5)

def launch_profile(profile: str, headless: bool, args: list[str], executable: str | None) -> str:
    if profile != "session":
        return profile

    settings = json.dumps({"headless": headless, "args": list(args), "executable": executable}, sort_keys=True)
    return f"work-agent-session-{hashlib.sha256(settings.encode()).hexdigest()[:12]}"


class BrowserConnection:
    def __init__(self, key: str) -> None:
        self.key = key
        self.browser: Any = None
        self.forward: PortForward | None = None
        self.lock = asyncio.Lock()
        self.shared: SharedContext | None = None


OnDownload = Callable[[str, str, dict[str, Any]], Awaitable[None]]


class BrowserContexts:
    def __init__(self, nodes: Any, on_download: OnDownload) -> None:
        self.nodes = nodes
        self.on_download = on_download
        self._playwright: Any = None
        self._playwright_manager: Any = None
        self._hosts: dict[str, BrowserConnection] = {}
        self._sessions: dict[tuple[str, str], BrowserContext] = {}
        self._lock = asyncio.Lock()

    async def playwright(self) -> Any:
        async with self._lock:
            if self._playwright is None:
                try:
                    from playwright.async_api import async_playwright
                except ImportError as error:
                    raise RuntimeError("Browser features require playwright; run pip install playwright") from error
                self._playwright_manager = async_playwright()
                self._playwright = await self._playwright_manager.start()
            return self._playwright

    @staticmethod
    def config_key(config: Browser) -> str:
        return config.model_dump_json()

    async def context_for(self, root_id: str, config: Browser, place: DownloadPlace) -> BrowserContext:
        key = (root_id, self.config_key(config))
        session = self._sessions.get(key)
        if session is None:
            session = self._sessions[key] = BrowserContext(self, root_id, config, place)

        await session.ensure()
        return session

    async def session_closing(self, session_id: str, root_id: str, top_level: bool) -> None:
        if top_level:
            await self.close_tree(root_id)
            return
        for key, tree in list(self._sessions.items()):
            if key[0] == root_id:
                await tree.forget_owner(session_id)

    async def close_tree(self, root_id: str) -> None:
        for key in [key for key in self._sessions if key[0] == root_id]:
            session = self._sessions.pop(key)
            with contextlib.suppress(Exception):
                await session.close()

    def _host_key(self, config: Browser, node: Any) -> str:
        launch = "session" if config.profile == "session" else config.profile
        return json.dumps(
            {"node": config.node, "instance": id(node) if node is not None else None, "cdp": config.cdp,
             "profile": launch, "headless": config.headless, "args": config.args, "executable": config.executable},
            sort_keys=True,
        )  # fmt: skip

    async def host(self, config: Browser, root_id: str) -> BrowserConnection:
        node = await self.nodes.get(config.node, root_id=root_id) if config.node else None
        key = self._host_key(config, node)
        async with self._lock:
            host = self._hosts.setdefault(key, BrowserConnection(key))

        async with host.lock:
            if host.browser is None or not host.browser.is_connected():
                host.browser = await self._connect(host, config, node)
                host.shared = None

        return host

    def forget_shared(self, shared: SharedContext) -> None:
        for host in self._hosts.values():
            if host.shared is shared:
                host.shared = None

    async def _connect(self, host: BrowserConnection, config: Browser, node: Any) -> Any:
        playwright = await self.playwright()
        if config.cdp:
            url = expand_env(config.cdp) if has_env_reference(config.cdp) else config.cdp
            return await playwright.chromium.connect_over_cdp(url)

        headless = config.headless if config.headless is not None else True
        options = BrowserOptions(
            profile=launch_profile(config.profile, headless, config.args, config.executable),
            headless=headless,
            args=tuple(config.args),
            executable=config.executable,
        )
        retries = list(CONNECT_RETRY_DELAYS)
        while True:
            port = await node.start_browser(options)

            if host.forward is not None:
                with contextlib.suppress(Exception):
                    await host.forward.close()

            host.forward = await node.forward_port(port)
            try:
                return await playwright.chromium.connect_over_cdp(f"http://{host.forward.address}")
            except Exception:
                if not retries:
                    raise
                await asyncio.sleep(retries.pop(0))

    async def close(self) -> None:
        for session in list(self._sessions.values()):
            with contextlib.suppress(Exception):
                await session.close()

        self._sessions.clear()

        for host in self._hosts.values():
            with contextlib.suppress(Exception):
                if host.browser is not None:
                    await host.browser.close()
            with contextlib.suppress(Exception):
                if host.forward is not None:
                    await host.forward.close()

        self._hosts.clear()

        if self._playwright_manager is not None:
            with contextlib.suppress(Exception):
                await self._playwright_manager.__aexit__(None, None, None)

        self._playwright = None
        self._playwright_manager = None
