from __future__ import annotations

import asyncio
import fnmatch
import ipaddress
import re
import socket
import time
from urllib.parse import urlsplit

from work_agent_sdk.browser.config import BrowserPolicy

PRIVATE_HOSTS = {"localhost", "metadata", "metadata.google.internal"}
PRIVATE_SUFFIXES = (".localhost", ".internal")
NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
ALLOWED_SCHEMES = ("http", "https", "ws", "wss")
DNS_CACHE_SECONDS = 60.0

_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_HOST_PORT = re.compile(r"^[^/?#:]+:\d+(?:[/?#]|$)")


def with_scheme(url: str) -> str:
    if "://" in url or (_SCHEME.match(url) and not _HOST_PORT.match(url)):
        return url
    return "https://" + url


def is_private_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        return False

    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped:
            address = address.ipv4_mapped
        elif address.sixtofour:
            address = address.sixtofour
        elif address in NAT64_PREFIX or int(address) >> 32 == 0:
            address = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)

    return not address.is_global or address.is_multicast


def is_private_host(host: str) -> bool:
    if host in PRIVATE_HOSTS or host.endswith(PRIVATE_SUFFIXES):
        return True
    return is_private_address(host)


def host_matches(host: str, port: int | None, patterns: list[str]) -> bool:
    candidates = [host, f"{host}:{port}" if port else host]
    for raw in patterns:
        pattern = raw.lower().rstrip(".")
        if ":" not in pattern and pattern.startswith("*.") and host.endswith(pattern[1:]):
            return True
        if any(fnmatch.fnmatchcase(candidate, pattern) for candidate in candidates):
            return True

    return False


class UrlRules:
    def __init__(
        self,
        allow: bool | list[str] = True,
        deny: list[str] | None = None,
        private: bool | list[str] = False,
    ) -> None:
        self.allow: bool | list[str] = list(allow) if isinstance(allow, (list, tuple)) else bool(allow)
        self.deny = list(deny or [])
        self.private: bool | list[str] = list(private) if isinstance(private, (list, tuple)) else bool(private)
        self._dns_cache: dict[str, tuple[float, bool]] = {}

    def __repr__(self) -> str:
        return f"UrlRules(allow={self.allow!r})"

    async def check(self, url: str) -> str | None:
        try:
            parts = urlsplit(url)
        except ValueError:
            return "网址无效"
        scheme = parts.scheme.lower()
        if scheme in ("about", "blob", "data") and url in ("about:blank",):
            return None
        if scheme not in ALLOWED_SCHEMES:
            return f"仅允许访问 http 或 https 网址（{scheme}: 不允许）"

        host = (parts.hostname or "").lower().rstrip(".")

        try:
            port = parts.port
        except ValueError:
            return "网址端口无效"

        if self.deny and host_matches(host, port, self.deny):
            return f"不允许访问 {host}"
        if isinstance(self.private, list) and host_matches(host, port, self.private):
            return None
        if self.allow is False:
            return "浏览器的网络访问已被禁止"
        if isinstance(self.allow, list) and not host_matches(host, port, self.allow):
            return f"{host} 不在允许访问的网站范围内"
        if self.private is True:
            return None
        if is_private_host(host) or await self._resolves_to_private(host):
            return f"不允许访问本机、内网或云服务器元数据地址，或域名无法解析（{host}）"
        return None

    async def _resolves_to_private(self, host: str) -> bool:
        cached = self._dns_cache.get(host)
        if cached is not None and time.time() - cached[0] < DNS_CACHE_SECONDS:
            return cached[1]

        try:
            loop = asyncio.get_running_loop()
            addresses = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            private = any(is_private_address(str(address[4][0])) for address in addresses)
        except OSError:
            private = True

        self._dns_cache[host] = (time.time(), private)
        return private


def url_rules(policy: BrowserPolicy) -> UrlRules:
    return UrlRules(policy.allow, policy.deny, policy.private)
