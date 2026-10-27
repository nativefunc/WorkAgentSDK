from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

# Tab state in the data of browser tool results; the model adapter layer uses it to build the provider's native state block
BROWSER_STATE = "browser_state"


@dataclass(frozen=True)
class Action:
    name: str
    schema: dict[str, Any]
    description: str
    # Doesn't change state (screen or page)
    read_only: bool = False
    # Not provided by default; enabled by the developer (the browser's run JavaScript, upload files, read console, read network requests)
    optional: bool = False
    # Browser: after running, wait for the page to settle (loaded, downloads written to disk) before returning
    settles: bool = False
    # Browser: reads page content; wait for the current document to finish parsing first, to avoid reading a half-loaded page
    reads_page: bool = False
    # Browser: acts on the tab list rather than a specific tab
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
