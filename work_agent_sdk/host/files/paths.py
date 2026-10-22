from __future__ import annotations

import ntpath
import posixpath
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from types import ModuleType

DATA_DIR = ".work-agent"

# 沙箱默认不可读的路径（~ 为执行节点的家目录）
DEFAULT_DENY_READ = (
    "~/.ssh",
    "~/.aws",
    "~/.gnupg",
    "~/.kube",
    "~/.docker",
    "~/.azure",
    "~/.config/gcloud",
    "~/.netrc",
    "~/.git-credentials",
    "~/.pypirc",
    "~/.npmrc",
    # 框架自身的目录：浏览器登录状态、Runner 数据和各会话的临时目录。当前会话的临时目录和技能目录规则更具体，仍可使用
    "~/.work-agent",
)


def local_system() -> str:
    if sys.platform == "win32":
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


@dataclass(frozen=True)
class PathStyle:
    system: str = "linux"

    @property
    def _module(self) -> ModuleType:
        return ntpath if self.system == "windows" else posixpath

    @property
    def windows(self) -> bool:
        return self.system == "windows"

    @property
    def ignore_case(self) -> bool:
        return self.system in ("macos", "windows")

    @property
    def sep(self) -> str:
        return self._module.sep

    def is_absolute(self, path: str) -> bool:
        if not self.windows:
            return path.startswith("/")

        drive, rest = ntpath.splitdrive(path)
        if drive.startswith(("\\\\", "//")):
            return True
        return bool(drive) and rest[:1] in ("\\", "/")

    def normalize(self, path: str) -> str:
        return self._module.normpath(path)

    def join(self, base: str, *parts: str) -> str:
        return self._module.normpath(self._module.join(base, *parts))

    def parent(self, path: str) -> str:
        return self._module.dirname(self.normalize(path))

    def name(self, path: str) -> str:
        return self._module.basename(self.normalize(path))

    def root_of(self, path: str) -> str:
        if not self.windows:
            return "/"

        drive = ntpath.splitdrive(self.normalize(path))[0]
        return drive + "\\" if drive else "\\"

    def is_root(self, path: str) -> bool:
        return self.same(path, self.root_of(path))

    def starts_at_home(self, path: str) -> bool:
        return path == "~" or path.startswith("~/") or (self.windows and path.startswith("~\\"))

    def expand_home(self, path: str, home: str) -> str:
        if path == "~":
            return home
        if self.starts_at_home(path):
            return self.join(home, path[2:])
        return path

    def absolute(self, path: str, home: str, base: str | None = None) -> str:
        path = self.expand_home(path, home)
        if self.is_absolute(path):
            return self.normalize(path)
        return self.join(base or home, path)

    def relative(self, path: str, start: str) -> str:
        if not self.inside(path, start):
            return path
        if self.same(path, start):
            return "."

        root = self.normalize(start)
        if not root.endswith(self.sep):
            root += self.sep

        return self.normalize(path)[len(root) :]

    def comparable(self, path: str) -> str:
        if self.windows:
            normalized = ntpath.normcase(ntpath.normpath(path))
            drive, rest = ntpath.splitdrive(normalized)
            # 仅有盘符或共享名（无后续部分）时，指其根目录
            return drive + "\\" if drive and not rest else normalized

        normalized = posixpath.normpath(path)
        return normalized.casefold() if self.ignore_case else normalized

    def same(self, a: str, b: str) -> bool:
        return self.comparable(a) == self.comparable(b)

    def inside(self, path: str, root: str) -> bool:
        path, root = self.comparable(path), self.comparable(root)
        if path == root:
            return True

        prefix = root if root.endswith(self.sep) else root + self.sep
        return path.startswith(prefix)


def local_style() -> PathStyle:
    return PathStyle(local_system())


@dataclass(frozen=True)
class NodePaths:
    home: str
    style: PathStyle

    @property
    def data_dir(self) -> str:
        return self.style.join(self.home, DATA_DIR)

    @property
    def tmp_root(self) -> str:
        return self.style.join(self.data_dir, "tmp")

    def tmp(self, root_session: str) -> str:
        return self.style.join(self.tmp_root, root_session)

    @property
    def transfers(self) -> str:
        return self.style.join(self.tmp_root, "transfers")

    @property
    def skills(self) -> str:
        return self.style.join(self.data_dir, "skills")

    @property
    def downloads_root(self) -> str:
        return self.style.join(self.data_dir, "downloads")

    def downloads(self, root_session: str) -> str:
        return self.style.join(self.downloads_root, root_session)

    def incoming(self, name: str) -> str:
        return self.style.join(self.downloads_root, f".incoming-{name}")

    @property
    def browser_root(self) -> str:
        return self.style.join(self.data_dir, "browser")

    def browser_profile(self, profile: str) -> str:
        return self.style.join(self.browser_root, profile)

    @property
    def framework_dirs(self) -> list[str]:
        return [self.tmp_root, self.skills, self.downloads_root]

    def absolute(self, path: str, base: str | None = None) -> str:
        return self.style.absolute(path, self.home, base)


@dataclass(kw_only=True)
class PathRules:
    style: PathStyle
    read: list[str] = field(default_factory=list)
    write: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    protected: Callable[[str], bool] | None = None
    exempt: list[str] = field(default_factory=list)

    def _inside(self, path: str, root: str) -> bool:
        return self.style.inside(path, root)

    def _closest(self, path: str, roots: Iterable[str]) -> str | None:
        matches = [root for root in roots if self._inside(path, root)]
        return max(matches, key=len) if matches else None

    def allowed(self, path: str, allow: Iterable[str]) -> bool:
        allowed = self._closest(path, allow)
        if allowed is None:
            return False

        denied = self._closest(path, self.deny)
        return denied is None or self._inside(allowed, denied)

    def can_read(self, path: str) -> bool:
        return self.allowed(path, [*self.read, *self.write, *self.exempt])

    def can_write(self, path: str) -> bool:
        if any(self._inside(path, root) for root in self.exempt):
            return self.allowed(path, self.exempt)
        if self.protected is not None and self.protected(path):
            return False
        return self.allowed(path, self.write)
