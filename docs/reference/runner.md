# Runner

## Runner

```python
from work_agent_sdk import Runner
```

```python
Runner(
    *,
    agents: Sequence[Agent] = (),
    data_dir: str = "~/.work-agent/runner",
    store: Store | None = None,
    nodes: Sequence[Node] | None = None,
    shared_folders: Sequence[SharedFolder] = (),
    extensions: Sequence[Toolset] = (),
    services: Sequence[Service] = (),
    models: Sequence[Model] = (),
    hooks: Sequence[Hooks] = (),
    secret_key: str | KeyProvider | None = None,
    device_tokens: DeviceTokens | None = None,
)
```

Runs agents and creates and stores sessions. Start and shut it down with `async with Runner(...) as runner:`.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `agents` | `Sequence[Agent]` | `()` | Agents |
| `data_dir` | `str` | `"~/.work-agent/runner"` | Data directory. Can be used by only one Runner at a time. See [Storage](storage.md) |
| `store` | `Store \| None` | `LocalStore` | Storage for sessions, events and the message queue. See [Store](storage.md#store) |
| `nodes` | `Sequence[Node] \| None` | `[Local()]` | Nodes. When set, only the listed nodes can be used; list `Local()` to use the local machine. See [Nodes](nodes.md) |
| `shared_folders` | `Sequence[SharedFolder]` | `()` | Shared folders. See [SharedFolder](nodes.md#sharedfolder) |
| `extensions` | `Sequence[Toolset]` | `()` | Toolsets loaded on demand, available to all agents. When the model supports tool search, the needed tools are loaded through `tool_search`; otherwise they are given to the model directly |
| `services` | `Sequence[Service]` | `()` | Custom services. See [Services](services.md) |
| `models` | `Sequence[Model]` | `()` | Models that can be switched to. See [update()](sessions.md#update) |
| `hooks` | `Sequence[Hooks]` | `()` | Hooks. See [Hooks](hooks.md) |
| `secret_key` | `str \| KeyProvider \| None` | `None` | Key for encrypting MCP tokens: a random string of at least 32 characters, supports `${ENV_VAR}`, requires `cryptography`; or a [`KeyProvider`](storage.md#keyprovider). When unset, MCP tokens are kept only in memory |
| `device_tokens` | `DeviceTokens \| None` | `SqliteDeviceTokens` | Storage for device tokens. See [Other storage interfaces](storage.md#other-storage-interfaces) |

### Attributes

| Name | Type | Description |
| :-- | :-- | :-- |
| `agents` | `list[Agent]` | Agents |
| `data_dir` | `Path` | Data directory |
| `nodes` | `Nodes` | Manages nodes. See [Nodes](nodes.md#nodes) |
| `extensions` | `Extensions` | Manages toolsets loaded on demand |

### Methods

| Method | Description |
| :-- | :-- |
| [`new_session(agent, ...)`](#new_session) | Create a session |
| [`session(session_id)`](#session) | Open an existing session |
| [`sessions(agent, status, top_level)`](#sessions) | List sessions |
| `events()` | Subscribe to events from all sessions. See [Events](sessions.md#session-events) |
| `service(kind)` | Return a service, e.g. `runner.service(MCPService)` |
| `start()` | Start the Runner. Called automatically with `async with` |
| `shutdown()` | Shut down the Runner. Called automatically with `async with` |

### new_session()

```python
async def new_session(
    agent: Agent | str | None = None,
    *,
    metadata: dict | None = None,
    model: str | None = None,
    thinking: str | None = None,
    workspace: Workspace | None = None,
    browser: Browser | None = None,
    computer: Computer | None = None,
    resources: dict | None = None,
) -> Session
```

Creates a session and returns a [`Session`](sessions.md#session).

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `agent` | `Agent \| str \| None` | `None` | Agent or agent name. May be omitted when the Runner has only one agent |
| `metadata` | `dict \| None` | `None` | Extra data for the session, such as the user it belongs to |
| `model` | `str \| None` | `None` | Model ID. Uses the agent's model when unset |
| `thinking` | `str \| None` | `None` | Thinking level. Uses the agent's setting when unset |
| `workspace` | `Workspace \| None` | `None` | Workspace. See [Workspace](workspace.md#workspace) |
| `browser` | `Browser \| None` | `None` | Browser. See [Browser](browser.md#browser) |
| `computer` | `Computer \| None` | `None` | Computer. See [Computer](computer.md#computer) |
| `resources` | `dict \| None` | `None` | Dict from custom service resource name to configuration. See [Services](services.md) |

### session()

```python
async def session(session_id: str) -> Session
```

Returns an existing session; it can be opened even after the Runner restarts. Raises `KeyError` if the session doesn't exist.

### sessions()

```python
async def sessions(*, agent: str | None = None, status: str | None = None, top_level: bool = True) -> list[Session]
```

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `agent` | `str \| None` | `None` | Agent name |
| `status` | `str \| None` | `None` | Session status. Values: `open` or `closed` |
| `top_level` | `bool` | `True` | Whether to list only top-level sessions |

## Examples

- [sessions/sessions.py](../../examples/sessions/sessions.py): reopen a session
- [apps/web_backend](../../examples/apps/web_backend): run the Runner inside a web framework
