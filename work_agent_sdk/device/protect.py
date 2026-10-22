from __future__ import annotations

from work_agent_sdk.host.files.paths import PathStyle

PROTECT_TEMPLATES = ("standard", "none")

# 无论位于哪一层目录都不允许修改的文件和目录
PROTECTED_FILES = frozenset(
    {
        ".bashrc",
        ".bash_profile",
        ".bash_login",  # 没有 .bash_profile 时登录 shell 执行
        ".bash_logout",
        ".zshenv",  # zsh 每次启动都执行，包括运行脚本的非交互 shell
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
# launchd 配置：放入的 plist 在登录或开机时自动执行。按小写比较（macOS 不区分大小写）
MACOS_PROTECTED_PAIRS = frozenset({("library", "launchagents"), ("library", "launchdaemons")})
# .git 中的钩子和配置（包括子模块和各工作树中的副本）
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
