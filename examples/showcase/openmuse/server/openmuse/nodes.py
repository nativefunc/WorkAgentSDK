from __future__ import annotations

from openmuse.db import User
from openmuse.state import app_state

LOCAL = "local"


def local_mode() -> bool:
    return app_state().settings.local


def node_of(user: User) -> str:
    return LOCAL if local_mode() else user.device


def online(user: User) -> bool:
    state = app_state()
    if state.runner is None:
        return False
    return state.runner.nodes.is_online(node_of(user))
