from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from work_agent_sdk.core.agent import Agent
    from work_agent_sdk.core.events import Event, EventBus
    from work_agent_sdk.core.hooks import Hooks
    from work_agent_sdk.core.secrets import KeyProvider
    from work_agent_sdk.core.service import NodeLookup, Service
    from work_agent_sdk.core.tool import Toolset
    from work_agent_sdk.store import Store


class RunnerCore(Protocol):
    store: Store
    secret_key: KeyProvider | None

    @property
    def nodes(self) -> NodeLookup: ...

    hooks: list[Hooks]
    started_at: float
    bus: EventBus
    data_dir: Path

    def agent(self, name: str) -> Agent: ...
    def model(self, model_id: str) -> Any: ...
    def provider(self, resource: str) -> Service | None: ...
    def services(self) -> list[Service]: ...
    def service(self, kind: type) -> Any: ...
    def extensions(self) -> list[Toolset]: ...
    def publish(self, event: Event) -> None: ...
