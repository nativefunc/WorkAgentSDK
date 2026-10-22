from __future__ import annotations

import inspect
import os
import re
import time
import uuid
from typing import Any

ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:16]}"


def now() -> float:
    return time.time()


def expand_env(value: str) -> str:
    missing = [name for name in ENV_REFERENCE.findall(value) if not os.environ.get(name)]
    if missing:
        raise LookupError(f"环境变量 {', '.join(missing)} 未设置")
    return ENV_REFERENCE.sub(lambda match: os.environ[match.group(1)], value)


def has_env_reference(value: Any) -> bool:
    return isinstance(value, str) and bool(ENV_REFERENCE.search(value))


def maybe_env(value: str) -> str:
    return expand_env(value) if has_env_reference(value) else value


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def head_and_tail(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text

    half = limit // 2
    omitted = len(text) - half * 2
    return f"{text[:half]}\n…（已省略中间 {omitted} 个字符）…\n{text[-half:]}"


def check_name(kind: str, name: str) -> str:
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        from work_agent_sdk.core.errors import ConfigError

        raise ConfigError(f"{kind}名称 {name!r} 不合法；仅允许字母、数字、_ 和 -，最长 64 个字符")
    return name


def matches_any(name: str, patterns: tuple[str, ...] | list[str]) -> bool:
    import fnmatch

    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)
