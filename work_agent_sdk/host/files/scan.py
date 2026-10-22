from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Iterable, Sequence

from work_agent_sdk.host.files.helper import BLOCK_SIZE
from work_agent_sdk.host.files.paths import local_style

Readable = Callable[[str], str]


def _real_path(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


# 目录哈希：涵盖目录中全部文件（相对路径与内容），按名称排序；符号链接按其指向的内容计算。
class TreeHash:
    def __init__(self) -> None:
        self._digest = hashlib.sha256()

    def begin(self, relative: str) -> None:
        self._digest.update(relative.encode() + b"\0")

    def add(self, piece: bytes) -> None:
        self._digest.update(piece)

    def end(self) -> None:
        self._digest.update(b"\0")

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def tree_hash(path: str, readable: Readable = _real_path) -> str:
    digest = TreeHash()

    def walk(directory: str, prefix: str, ancestors: frozenset[str]) -> None:
        for name in sorted(os.listdir(directory)):
            relative = f"{prefix}{name}"
            real = readable(os.path.join(directory, name))
            if os.path.isdir(real):
                if real in ancestors:
                    raise ValueError(f"{relative} 链接回自身的上级目录（形成环）")
                walk(real, relative + "/", ancestors | {real})
                continue

            digest.begin(relative)

            with open(real, "rb") as file:
                while piece := file.read(BLOCK_SIZE):
                    digest.add(piece)

            digest.end()

    root = readable(path)
    walk(root, "", frozenset({root}))
    return digest.hexdigest()


def find_manifests(
    workspace: str,
    roots: Sequence[str],
    manifest: str,
    max_size: int,
    *,
    unchanged: str | None = None,
    read: Iterable[str] = (),
    readable: Readable = _real_path,
) -> dict[str, object]:
    # 子目录与 manifest 的真实路径须在 workspace 内，以免经链接读到工作区之外的文件
    style = local_style()
    found: list[tuple[str, list[float], str]] = []

    try:
        inside_root = readable(workspace)
    except OSError:
        roots = ()
        inside_root = ""

    for root in roots:
        try:
            real_root = readable(root)
            names = sorted(os.listdir(real_root))
        except OSError:
            continue

        for name in names:
            try:
                directory = readable(os.path.join(real_root, name))
                if not os.path.isdir(directory) or not style.inside(directory, inside_root):
                    continue

                file = readable(os.path.join(directory, manifest))
                info = os.stat(file)
            except OSError:
                continue

            if not os.path.isfile(file) or info.st_size > max_size or not style.inside(file, inside_root):
                continue

            found.append((style.join(root, name), [info.st_mtime, float(info.st_size)], file))

    digest = hashlib.sha256(
        repr([(directory, fingerprint) for directory, fingerprint, _ in found]).encode()
    ).hexdigest()
    if digest == unchanged:
        return {"digest": digest, "entries": None}

    wanted = set(read)
    entries: list[dict[str, object]] = []
    for directory, fingerprint, file in found:
        text = None
        if directory in wanted:
            try:
                with open(file, "rb") as handle:
                    text = handle.read(max_size).decode("utf-8", errors="replace")
            except OSError:
                continue
        entries.append({"dir": directory, "fingerprint": fingerprint, "text": text})

    return {"digest": digest, "entries": entries}
