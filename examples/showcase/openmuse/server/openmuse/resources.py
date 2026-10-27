from __future__ import annotations

from work_agent_sdk import SRT, Browser, BrowserPolicy, Computer, ComputerPolicy, Workspace
from work_agent_sdk.host.files.paths import DEFAULT_DENY_READ

from openmuse.config import Settings
from openmuse.db import User


def _node(user: User, settings: Settings) -> str:
    return "local" if settings.local else user.device


def _workspace_path(user: User, settings: Settings) -> str:
    return f"{settings.workspace_path}/{user.device}" if settings.local else settings.workspace_path


def workspace_for(user: User, settings: Settings) -> Workspace:
    deny_read = [*DEFAULT_DENY_READ, settings.workspace_path.rsplit("/", 1)[0] + "/audit.jsonl", "~/.openmuse"]
    if settings.sandbox_deny_home:
        deny_read.append("~")

    sandbox_settings: dict = {}
    if settings.local:
        sandbox_settings = {
            "network": {
                "deniedDomains": [
                    "169.254.169.254",
                    "metadata.google.internal",
                    "metadata.azure.com",
                    "100.100.100.200",
                ],
                "allowLocalBinding": False,
                "allowAllUnixSockets": False,
            },
            "filesystem": {"allowGitConfig": False},
        }

    return Workspace(
        _workspace_path(user, settings),
        node=_node(user, settings),
        sandbox=SRT(
            network=list(settings.sandbox_network),
            deny_read=deny_read,
            protect=[".agents/", ".claude/", ".openmuse/"],
            settings=sandbox_settings,
        ),
    )


def browser_for(user: User, settings: Settings) -> Browser:
    generation = int(user.settings.get("browser_profile") or 1)
    return Browser(
        node=_node(user, settings),
        profile=f"openmuse-{user.id}-{generation}" if settings.local else f"openmuse-{generation}",
        policy=BrowserPolicy.standard(
            deny=list(settings.browser_deny),
            private=False,
            enable=["file_upload"],
        ),
        headless=settings.browser_headless,
        download_dir=f"{_workspace_path(user, settings)}/downloads",
    )


def computer_for(user: User, settings: Settings) -> Computer:
    return Computer(
        node=_node(user, settings),
        policy=ComputerPolicy.standard(
            deny=list(settings.computer_deny) or None,
            system_keys="ask",
            hold="turn",
        ),
    )


def session_resources(user: User, settings: Settings) -> dict:
    return {
        "workspace": workspace_for(user, settings),
        "browser": browser_for(user, settings),
        "computer": computer_for(user, settings),
    }
