from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from work_agent_sdk.browser.config import Browser
from work_agent_sdk.core.errors import ConfigError
from work_agent_sdk.host.files.paths import PathStyle

UNSAFE_CHARACTERS = re.compile(r"[\x00-\x1f\x7f/\\:*?\"<>|]+")
INVISIBLE = {"Cf", "Cc", "Co", "Cs"}
# Device names reserved by Windows; can't be used as file names regardless of extension
RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
MAX_NAME_BYTES = 200


def safe_file_name(name: str, fallback: str = "download") -> str:
    name = unicodedata.normalize("NFC", os.path.basename(str(name).replace("\\", "/")))
    name = "".join(char for char in name if unicodedata.category(char) not in INVISIBLE)
    name = UNSAFE_CHARACTERS.sub("_", name).strip(" .")
    if not name:
        name = fallback

    stem, extension = os.path.splitext(name)
    if len(extension.encode()) > 20:
        stem, extension = name, ""
    if stem.lower() in RESERVED or stem.startswith("-"):
        stem = f"_{stem}"

    budget = MAX_NAME_BYTES - len(extension.encode())
    encoded = stem.encode()
    if len(encoded) > budget:
        stem = encoded[:budget].decode(errors="ignore").rstrip(" .") or fallback

    return stem + extension


def numbered_name(name: str, index: int) -> str:
    stem, extension = os.path.splitext(name)
    return f"{stem} ({index}){extension}"


@dataclass
class DownloadPlace:
    mode: str
    node: Any = None
    # Download directory on the node the browser runs on
    directory: str | None = None
    # Whether it is the framework's default directory; the default directory is deleted when the top-level session closes
    temporary: bool = False
    style: PathStyle | None = None


async def resolve_place(nodes: Any, config: Browser, root_id: str) -> DownloadPlace:
    if not config.downloads:
        return DownloadPlace("deny")
    if not config.can_manage_downloads:
        return DownloadPlace("browser")

    node = await nodes.get(config.node, root_id=root_id)
    info = await node.info()
    style = info.style
    if config.download_dir is None:
        directory, temporary = info.node_paths.downloads(root_id), True
    else:
        directory, temporary = style.absolute(config.download_dir, info.home), False

    try:
        await node.make_dir(directory)
    except PermissionError as error:
        raise ConfigError(f"The browser can't use download directory {directory}: {error}") from None

    directory = (await node.stat(directory)).real_path
    return DownloadPlace("save", node, directory, temporary, style)
