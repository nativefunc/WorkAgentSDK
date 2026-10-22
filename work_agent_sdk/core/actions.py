from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

# 浏览器工具结果 data 中的标签页状态，模型适配层据此生成厂商原生的状态块
BROWSER_STATE = "browser_state"


@dataclass(frozen=True)
class Action:
    name: str
    schema: dict[str, Any]
    description: str
    # 不改变状态（屏幕或页面）
    read_only: bool = False
    # 默认不提供，由开发者启用（浏览器的执行 JavaScript、上传文件、读取控制台、读取网络请求）
    optional: bool = False
    # 浏览器：执行后等待页面稳定（加载完成、下载落盘）再返回
    settles: bool = False
    # 浏览器：读取页面内容，执行前等待当前文档解析完成，避免读到正在加载的半个页面
    reads_page: bool = False
    # 浏览器：作用于标签页列表，而非某个标签页
    tabs: bool = False


class ActionCatalog:
    def __init__(self, toolset: str, actions: list[Action]) -> None:
        self.toolset = toolset
        self._actions = {action.name: action for action in actions}

    def __repr__(self) -> str:
        return f"ActionCatalog({self.toolset!r})"

    def __getitem__(self, name: str) -> Action:
        return self._actions[name]

    def __contains__(self, name: object) -> bool:
        return name in self._actions

    def __iter__(self) -> Iterator[Action]:
        return iter(self._actions.values())

    def get(self, name: str) -> Action | None:
        return self._actions.get(name)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._actions)

    @property
    def read_only(self) -> frozenset[str]:
        return frozenset(action.name for action in self if action.read_only)

    @property
    def optional(self) -> frozenset[str]:
        return frozenset(action.name for action in self if action.optional)
