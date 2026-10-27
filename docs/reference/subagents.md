# Subagents

```python
from work_agent_sdk import Subagents
```

## Subagents

```python
Subagents(
    foreground: Sequence[Agent] = (),
    background: Sequence[Agent] = (),
    *,
    dynamic: Agent | None = None,
    max_background: int = 4,
    agent_description: str | None = None,
)
```

Toolset that lets the main agent delegate to subagents; add it to the main agent's `tools` parameter. Subagents run in child sessions and share the main agent's workspace, browser and computer. They must set `description`, which the main agent uses to choose among them.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `foreground` | `Sequence[Agent]` | `()` | Subagents that run in the foreground. The main agent continues after they finish; several delegated at once run in parallel |
| `background` | `Sequence[Agent]` | `()` | Subagents that run in the background, concurrently with the main agent. When one finishes, its result is sent to the main agent as a message and the main agent answers again; get that answer with [`events()`](sessions.md#events) |
| `dynamic` | `Agent \| None` | `None` | Template agent. When delegating, the main agent picks which of its tools the subagent may use and whether it runs in the foreground or background |
| `max_background` | `int` | `4` | Maximum number of background subagents running at once |
| `agent_description` | `str \| None` | `None` | Replaces the description of the `agent` tool |

Set at least one of `foreground`, `background` and `dynamic`.

| Tool | Description |
| :-- | :-- |
| `agent` | Delegate to a subagent |
| `message_agent` | Send a message to a background subagent. Provided when `background` or `dynamic` is set |
| `close_agent` | Close a background subagent. Provided when `background` or `dynamic` is set |
| `list_agents` | List subagents and running background subagents. Provided when `background` or `dynamic` is set |

## TaskControl

Methods of `ctx.tasks`, for creating child sessions from tools. Agents used by child sessions must be added to `Runner`'s `agents` parameter.

| Method | Description |
| :-- | :-- |
| `spawn(agent, background=False, tools=None)` | Create a child session and return its ID. `tools` are the names of tools the child session may use |
| `wait(task_id, prompt)` | Send a task to a child session, wait for it to finish, and return a [`TaskResult`](#taskresult). Waits the same way as [`ctx.wait_for()`](requests.md) |
| `send(task_id, prompt)` | Send a message to a child session without waiting |
| `close(task_id)` | Close a child session |
| `get(task_id)` | Return the child session's [`SessionInfo`](sessions.md#sessioninfo). Returns `None` if it doesn't exist |
| `list()` | Return the `SessionInfo` of all child sessions |

## TaskResult

| Field | Type | Description |
| :-- | :-- | :-- |
| `task_id` | `str` | Child session ID |
| `agent` | `str` | Subagent name |
| `status` | `str` | Status. Values: `completed`, `error`, `rejected`, `stopped` or `cancelled` |
| `text` | `str` | The subagent's answer |
| `data` | `Any` | Structured data |
| `error` | `ErrorInfo \| None` | Error information. See [ErrorInfo](sessions.md#errorinfo) |

## Examples

- [subagents/subagents.py](../../examples/subagents/subagents.py): foreground, background and on-demand subagents; getting the answer after a background subagent finishes
- [subagents/tasks.py](../../examples/subagents/tasks.py): create child sessions from tools and code
