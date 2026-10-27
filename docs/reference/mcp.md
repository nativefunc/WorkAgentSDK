# MCP

```python
from work_agent_sdk import MCP, MCPService, OAuth
```

## MCP

```python
MCP(
    name: str,
    *,
    url: str | None = None,
    headers: dict[str, str] = {},
    auth: OAuth | None = None,
    command: str | None = None,
    args: list[str] = [],
    env: dict[str, str] = {},
    runs_on: str = "runner",
    unsandboxed: bool = False,
    description: str | None = None,
    trust_hints: bool = False,
    resources: bool = False,
    timeout: float = 30,
    tool_timeout: float = 600,
)
```

Connects to one MCP server; add it to the `tools` parameter of `Agent`. Use `url` to connect to a remote MCP server, or `command` to start a local one. The model sees tool names as `mcp__<name>__<tool name>`, e.g. `mcp__docs__search`.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `name` | `str` | Required | Name, used in tool names. Letters, digits, `_` and `-` only, up to 40 characters |
| `url` | `str \| None` | `None` | Address of the remote MCP server |
| `headers` | `dict[str, str]` | `{}` | Request headers. Supports `${ENV_VAR}`. Only applies to `url` |
| `auth` | `OAuth \| None` | `None` | OAuth settings. Only applies to `url`. See [OAuth](#oauth) |
| `command` | `str \| None` | `None` | Command that starts the local MCP server |
| `args` | `list[str]` | `[]` | Command arguments |
| `env` | `dict[str, str]` | `{}` | Environment variables for the command. Supports `${ENV_VAR}` |
| `runs_on` | `str` | `"runner"` | Where the local MCP server runs; see the table below |
| `unsandboxed` | `bool` | `False` | Whether to run outside the sandbox. Only applies to `runs_on="workspace"` |
| `description` | `str \| None` | `None` | Description of the MCP server, prepended to each tool's description |
| `trust_hints` | `bool` | `False` | Whether to use the `read_only` and `destructive` hints from the MCP server. MCP server tools are all marked `open_world` |
| `resources` | `bool` | `False` | Whether to provide the resource tools `mcp__<name>__list_resources` and `mcp__<name>__read_resource` |
| `timeout` | `float` | `30` | Connection timeout (seconds) |
| `tool_timeout` | `float` | `600` | Tool call timeout (seconds) |

| `runs_on` | Runs on | Sandbox | Sessions |
| :-- | :-- | :-- | :-- |
| `"runner"` | Local machine | None | Shared by all sessions; data is shared between sessions |
| `"workspace"` | The session's workspace. Unavailable when the session has no workspace | Workspace sandbox | One per session |

Exactly one of `url` and `command` must be set.

## OAuth

```python
OAuth(*, redirect_uri: str, scopes: list[str] = [], client_id: str | None = None, client_secret: str | None = None, client_name: str = "work-agent-sdk", trusted_origins: list[str] = [], state_ttl: float = 600)
```

Set this when the MCP server needs user authorization. If the user hasn't authorized, the session issues an [`Authorization`](#authorization) request; after the user opens its `url` and completes authorization, the browser is redirected to `redirect_uri`, where you call [`complete_authorization()`](#mcpservice) and the agent continues. Tokens are stored per MCP server and shared by all sessions; see `Runner`'s [`secret_key`](runner.md#runner) for how they are stored.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `redirect_uri` | `str` | Required | Address to redirect to after authorization |
| `scopes` | `list[str]` | `[]` | Scopes to request |
| `client_id` | `str \| None` | `None` | Client ID. Registered automatically when unset |
| `client_secret` | `str \| None` | `None` | Client secret |
| `client_name` | `str` | `"work-agent-sdk"` | Client name used for automatic registration |
| `trusted_origins` | `list[str]` | `[]` | Authorization server addresses on a different domain from the MCP server |
| `state_ttl` | `float` | `600` | How long the authorization page URL stays valid (seconds) |

## MCPService

Service returned by `runner.service(MCPService)`. `server` is the MCP server name.

| Method | Description |
| :-- | :-- |
| `complete_authorization(state, code=None, error=None)` | Complete authorization; the arguments are the query parameters received at `redirect_uri`. The result's `ok` says whether it succeeded and `error` gives the reason for failure |
| `authorize_url(server)` | Start authorization outside a session; returns the authorization page URL |
| `status(server)` | Return the authorization status. Values: `authorized`, `required` or `not_needed` |
| `revoke(server)` | Revoke the token and disconnect; returns whether the authorization server confirmed the revocation |
| `disconnect(server)` | Disconnect; reconnects on next use |

## Authorization

Request issued by the session when user authorization is needed; answered by the backend.

| Field | Type | Description |
| :-- | :-- | :-- |
| `server` | `str` | MCP server name |
| `url` | `str` | Authorization page URL |

## Examples

- [mcp/mcp.py](../../examples/mcp/mcp.py): connect to a remote MCP server, start a local MCP server, run it in the workspace
- [apps/mcp_oauth](../../examples/apps/mcp_oauth): OAuth authorization
