from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from work_agent_sdk import Runner

    from openmuse.config import Settings
    from openmuse.db import Database
    from openmuse.relay import Relay


@dataclass
class AppState:
    settings: Settings
    db: Database
    runner: Runner | None = None
    relay: Relay | None = None
    model: Any = None


_state: AppState | None = None


def set_app_state(state: AppState | None) -> None:
    global _state
    _state = state


def app_state() -> AppState:
    if _state is None:
        raise RuntimeError("OpenMuse hasn't started yet")
    return _state
