from __future__ import annotations

from work_agent_sdk.host.files.paths import PathStyle

PROTECT_TEMPLATES = ("standard", "none")

PROTECTED_FILES = frozenset(
    {
        ".bashrc",
        ".bash_profile",
        ".bash_login",
        ".bash_logout",
        ".zshenv",
        ".zshrc",
        ".zprofile",
        ".zlogin",
        ".zlogout",
        ".profile",
        ".gitconfig",
        ".gitmodules",
        ".ripgreprc",
        ".mcp.json",
    }
)
PROTECTED_DIRS = frozenset({".vscode", ".idea"})
PROTECTED_PAIRS = frozenset({(".claude", "commands"), (".claude", "agents")})

MACOS_PROTECTED_PAIRS = frozenset({("library", "launchagents"), ("library", "launchdaemons")})

PROTECTED_IN_GIT = frozenset({"hooks", "config", "config.worktree"})


def is_protected(style: PathStyle, path: str) -> bool:
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    if style.ignore_case:
        parts = [part.casefold() for part in parts]

    for index, name in enumerate(parts):
        if name in PROTECTED_FILES or name in PROTECTED_DIRS:
            return True
        if index + 1 < len(parts) and (name, parts[index + 1]) in PROTECTED_PAIRS:
            return True
        if style.system == "macos" and index + 1 < len(parts) and (name, parts[index + 1]) in MACOS_PROTECTED_PAIRS:
            return True
        if name == ".git" and any(part in PROTECTED_IN_GIT for part in parts[index + 1 :]):
            return True

    return False
