# Hooks

```python
from work_agent_sdk import Continue, Deny, Hooks, Reply, only_tools
```

## Hooks

Subclass `Hooks` and implement the methods you need. Add them to the `hooks` parameter of `Agent`, `Toolset` or `Runner`; the scope differs:

| Added to | Scope |
| :-- | :-- |
| `Agent(hooks=[...])` | This agent |
| `Toolset(hooks=[...])` | Agents that use this toolset |
| `Runner(hooks=[...])` | All agents |

### Methods

| Method | When it runs | If the hook raises |
| :-- | :-- | :-- |
| `before_turn(ctx, message)` | Before the message enters the session | The turn ends with `error` |
| `before_model(ctx, request)` | Before each model call | The turn ends with `error` |
| `after_model(ctx, message)` | After each model response | The turn ends with `error` |
| `before_tool(ctx, call)` | After tool arguments pass validation, before the tool runs | The tool does not run; the model receives an error |
| `after_tool(ctx, call, result)` | After each tool result, including denied and failed calls. Not run when argument validation fails | The tool result is replaced with an error |
| `before_turn_end(ctx, message)` | After the model gives its final answer | The turn ends with `error` |
| `on_model_error(ctx, request, error)` | When a model call still fails after automatic retries | The turn ends with `error` |

| Parameter | Type | Description |
| :-- | :-- | :-- |
| `ctx` | `Context` | Context. See [Context](tools.md#context) |
| `message` | `Message` | In `before_turn`, the message entering the session; in `after_model` and `before_turn_end`, the model's response |
| `request` | `ModelRequest` | Model request. See [ModelRequest](#modelrequest) |
| `call` | `ToolCall` | Tool call. See [ToolCall](#toolcall) |
| `result` | `ToolResult` | Tool result. See [ToolResult](tools.md#toolresult) |
| `error` | `ModelError` | Model error. See [ModelError](#modelerror) |

### Return values

| Method | Return value | Effect |
| :-- | :-- | :-- |
| All methods | `None` | Continue unchanged |
| `before_turn` | Modified message | The modified message enters the session |
| `before_turn` | `Deny` | The turn ends with `rejected` |
| `before_turn` | `Reply` | The model is not called; `content` becomes the answer |
| `before_model` | Modified `request` | The model is called with the modified request, e.g. truncated `messages` or a different `model` |
| `before_model` | `Deny` | The turn ends with `rejected` |
| `before_model` | `Reply` | `content` replaces the model's response |
| `after_model` | Modified message | Replaces the model's response |
| `before_tool` | Modified `call` | The tool runs with the modified arguments. `name` cannot be changed |
| `before_tool` | `Deny` | The tool does not run; `message` is sent to the model as an error result |
| `before_tool` | `Reply` | The tool does not run; `content` becomes the tool result |
| `after_tool` | Modified `ToolResult` | Replaces the tool result |
| `before_turn_end` | `Continue` | The model receives `prompt` and continues answering. At most 5 times per turn |
| `on_model_error` | Modified `request` | The model is called again with this request, e.g. switching to a fallback model. If it fails again the turn ends with `error` |
| `on_model_error` | `AssistantMessage` or string | Replaces the model's response |

### Multiple hooks

When a method has several hooks, they run in the order agent, toolset, Runner.

| Method | With multiple hooks |
| :-- | :-- |
| `before_turn`, `before_model`, `before_tool` | Modified values are passed along in order. When one returns `Deny` or `Reply`, later hooks do not run |
| `after_model`, `after_tool` | Modified values are passed along in order |
| `before_turn_end`, `on_model_error` | The first return value that is not `None` is used |

## only_tools()

```python
def only_tools(*patterns: str)
```

Decorates `before_tool` or `after_tool` so it only handles tools with matching names. Names support the `*` wildcard, e.g. `@only_tools("run_sql", "mcp__*")`.

## Deny

```python
Deny(message: str, *, code: str | None = None, data: Any = None)
```

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `message` | `str` | Required | Reason for the denial |
| `code` | `str \| None` | `None` | Error code. `denied` when unset |
| `data` | `Any` | `None` | Extra data |

## Reply

```python
Reply(content: Any)
```

`content` is the answer or tool result.

## Continue

```python
Continue(prompt: str)
```

`prompt` is the prompt sent to the model.

## ToolCall

| Field | Type | Description |
| :-- | :-- | :-- |
| `id` | `str` | Call ID |
| `name` | `str` | Tool name |
| `args` | `dict` | Tool arguments |

## ModelRequest

| Field | Type | Description |
| :-- | :-- | :-- |
| `model` | `Model` | Model in use |
| `system` | `str` | System prompt |
| `messages` | `list[Message]` | Messages sent to the model |
| `tools` | `list[dict]` | Tool definitions |
| `thinking` | `str` | Thinking level |
| `settings` | `ModelSettings` | Model parameters. See [ModelSettings](models.md#modelsettings) |
| `output_schema` | `dict \| None` | JSON Schema of the answer |

## ModelError

| Field | Type | Description |
| :-- | :-- | :-- |
| `code` | `str` | Error category, e.g. `rate_limit`, `overloaded`, `auth`, `context_overflow` |
| `message` | `str` | Error description |
| `status` | `int \| None` | HTTP status code |
| `retry_after` | `float \| None` | Wait time suggested by the model provider (seconds) |
| `retryable` | `bool` | Whether it can be retried automatically |

## Examples

- [human_in_the_loop/hooks.py](../../examples/human_in_the_loop/hooks.py): answer commands without the model, pick the model per user plan, block writes to production, audit and truncate tool results, make the model verify its changes, switch to a fallback model
- [workspace/sandbox.py](../../examples/workspace/sandbox.py): ask the user to confirm before running commands outside the sandbox
