# Services

```python
from work_agent_sdk import Service
```

## Service

Subclass `Service`, set `provides`, and implement the methods you need. Tools get the resource with `await ctx.resource()`. Add the service to `Runner`'s `services`, or list it in a `Toolset`'s class attribute `needs` (it is added to the Runner automatically when that toolset is used). Pass the configuration in `resources` when creating a session (a pydantic model or an object providing `to_config()`).

### Attributes

| Name | Type | Description |
| :-- | :-- | :-- |
| `provides` | `str \| None` | Name of the resource provided |
| `api` | `RunnerAPI` | See [RunnerAPI](#runnerapi). Available after `attach()` |

### Resource methods

| Method | Description |
| :-- | :-- |
| `check(config)` | Validate the resource configuration when a session is created; raise `ConfigError` if invalid |
| `bind(session)` | Create and return the resource. Called the first time a session uses the resource |
| `unbind(session, bound)` | Release the resource. Called when the session closes; `bound` is the return value of `bind()` |
| `ready(session)` | Return whether the resource can be used right away. When it returns `False`, `ctx.resource(name, wait=False)` returns `None` |
| `facts(session)` | Return the state of the resource; called before each turn. Returning `None` tells the model nothing; identical values from the previous turn are not sent again |
| `render(facts)` | Turn the return value of `facts()` into text sent to the model |
| `config_of(value)` | Turn the configuration in `resources` into a dict stored in the session. Supports pydantic models and `to_config()` by default |

### Lifecycle methods

Implement as needed.

| Method | When it is called |
| :-- | :-- |
| `attach(api)` | When the service is added to the Runner |
| `runner_started()` | After the Runner starts |
| `runner_stopping()` | Before the Runner shuts down |
| `runner_stopped()` | After the Runner shuts down |
| `session_started(session)` | After a session is created, including forked sessions and child sessions |
| `turn_started(session, turn_id, phase)` | When a turn starts or continues. `phase` values: `new` (a new turn), `resume` (continuing after a request is answered) or `recover` (continuing after the backend restarts) |
| `turn_ended(session, result)` | When a turn ends |
| `call_cancelled(session, call_id)` | When a tool call is cancelled |
| `session_stopped(session, everything)` | After `stop()` is called |
| `session_closing(session)` | When a session closes |
| `session_deleted(session)` | When a session is deleted |
| `toolset_added(toolset)` | When an on-demand toolset is added |
| `toolset_removed(toolset)` | When an on-demand toolset is removed |

## RunnerAPI

Attributes and methods of `service.api`.

| Attribute | Type | Description |
| :-- | :-- | :-- |
| `secret_key` | `KeyProvider \| None` | The Runner's `secret_key`. See [KeyProvider](storage.md#keyprovider) |
| `nodes` | `NodeLookup` | Look up nodes. `await nodes.get(name, root_id=...)` returns a node; `nodes.online(name, root_id=...)` returns whether it is online |

| Method | Description |
| :-- | :-- |
| `files(name)` | Return the service's data directory `data_dir/ext/<name>` |
| `service(kind)` | Return another service |
| `session(session_id)` | Return the session's [SessionRef](#sessionref). Returns `None` if the session doesn't exist |
| `descendants(session_id)` | Return the IDs of all descendant sessions |
| `lineage(session_id)` | Return the IDs from the top-level session down to this session |
| `resource(session_id, name)` | Return a session's resource |
| `update_resource(session_id, name, config)` | Change a session's resource configuration |
| `model(session_id)` | Return the model the session uses |
| `add_message(session_id, message)` | Add a `CustomMessage` to a session |
| `update_message(session_id, message_id, ...)` | Update a `CustomMessage` |
| `complete_message(session_id, message_id, ...)` | Finish an in-progress `CustomMessage` |
| `enqueue(session_id, message, source, metadata=None)` | Send a `CustomMessage` to a session; the agent answers when it receives it. `source` becomes the turn's `TurnStarted.source` |
| `answer(session_id, request_id, value)` | Answer a request |
| `pending(session_id)` | Return requests awaiting an answer |
| `run_in_background(coroutine)` | Start a background task. Cancelled when the Runner shuts down |

## SessionRef

Session information passed to service methods.

| Field | Type | Description |
| :-- | :-- | :-- |
| `id` | `str` | Session ID |
| `root_id` | `str` | ID of the top-level session |
| `parent_id` | `str \| None` | ID of the parent session |
| `agent` | `str` | Agent name |
| `resources` | `dict` | Dict from resource name to configuration |
| `metadata` | `dict` | Extra data of the session |
| `top_level` | `bool` | Whether it is a top-level session |

## Examples

- [advanced/custom_service](../../examples/advanced/custom_service): provide a SQLite database and SQL tools to sessions, check inventory in the background
