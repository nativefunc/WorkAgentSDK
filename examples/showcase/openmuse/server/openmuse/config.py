from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    model: str
    model_api: str
    dashscope_base_url: str | None
    compatible_base_url: str
    thinking: str

    data_dir: Path

    public_url: str | None

    timezone: str

    workspace_path: str

    node: str

    sandbox_network: list[str]
    sandbox_deny_home: bool

    browser_deny: list[str]
    browser_headless: bool

    computer_deny: list[str]

    max_upload_bytes: int = 20 * 1024 * 1024

    @property
    def downloads_path(self) -> str:
        return f"{self.workspace_path}/downloads"

    @property
    def local(self) -> bool:
        return self.node == "local"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def runner_dir(self) -> Path:
        return self.data_dir / "runner"

    @property
    def database(self) -> Path:
        return self.data_dir / "openmuse.db"


def _node(value: str) -> str:
    value = value.strip().lower() or "device"
    if value not in ("device", "local"):
        raise ValueError(f"OPENMUSE_NODE must be device or local, not {value!r}")
    return value


def load_settings() -> Settings:
    _load_dotenv(SERVER_DIR / ".env")
    data_dir = Path(os.path.expanduser(os.environ.get("OPENMUSE_DATA_DIR", str(SERVER_DIR / "data")))).resolve()
    return Settings(
        model=os.environ.get("OPENMUSE_MODEL", "qwen3.7-plus"),
        model_api=os.environ.get("OPENMUSE_MODEL_API", "dashscope"),
        dashscope_base_url=os.environ.get("DASHSCOPE_BASE_URL") or None,
        compatible_base_url=os.environ.get(
            "DASHSCOPE_COMPATIBLE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        thinking=os.environ.get("OPENMUSE_THINKING", "off"),
        data_dir=data_dir,
        public_url=(os.environ.get("OPENMUSE_PUBLIC_URL") or "").rstrip("/") or None,
        timezone=os.environ.get("OPENMUSE_TIMEZONE", "Asia/Shanghai"),
        workspace_path=os.environ.get("OPENMUSE_DEVICE_WORKSPACE", "~/OpenMuse/workspace").rstrip("/"),
        node=_node(os.environ.get("OPENMUSE_NODE", "device")),
        sandbox_network=_list("OPENMUSE_SANDBOX_NETWORK", "pypi.org,files.pythonhosted.org"),
        sandbox_deny_home=_bool("OPENMUSE_SANDBOX_DENY_HOME", True),
        browser_deny=_list("OPENMUSE_BROWSER_DENY", ""),
        browser_headless=_bool("OPENMUSE_BROWSER_HEADLESS", True),
        computer_deny=_list("OPENMUSE_COMPUTER_DENY", ""),
    )
