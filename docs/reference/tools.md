# Tools

```python
from work_agent_sdk import Tool, ToolError, ToolResult, Toolset, tool
```

## tool()

```python
def tool(
    *,
    description: str | Callable,
    name: str | None = None,
    parallel: bool = False,
    timeout: float | None = None,
    end_turn: bool = False,
    annotations: dict | None = None,
    requires: Sequence[str] = (),
    client: bool = False,
    output_schema: dict | None = None,
)
```

Decorator that turns a function into a tool; returns a [`Tool`](#tool-1).

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `description` | `str \| Callable` | Required | Description of the tool, or a function returning it |
| `name` | `str \| None` | Function name | Tool name |
| `parallel` | `bool` | `False` | Whether it can run at the same time as other tools |
| `timeout` | `float \| None` | `None` | Timeout (seconds) |
| `end_turn` | `bool` | `False` | Whether to end the turn after it runs |
| `annotations` | `dict \| None` | `None` | Tool properties, e.g. `{"destructive": True}`. See [Tool properties](#tool-properties) |
| `requires` | `Sequence[str]` | `()` | Resources it needs, e.g. `"workspace"`. When the session lacks them, the model doesn't see this tool |
| `client` | `bool` | `False` | Whether the frontend runs it. When `True`, the function body doesn't run; when the model calls the tool, the session issues a [`ClientTool`](requests.md#clienttool) request |
| `output_schema` | `dict \| None` | `None` | JSON Schema of `data` in the result |

### Function parameters

The SDK generates the JSON Schema for tool parameters from the function's parameter names, type annotations and defaults. Parameters without defaults are required. Parameter types can be pydantic models, `Literal`, lists and dicts. Use `Annotated[str, Field(description=...)]` to add parameter descriptions and constraints.

When the first parameter is named `ctx` or annotated as `Context`, the SDK passes in the [`Context`](#context), and this parameter doesn't appear in the JSON Schema.

### Function return values

| Return value | What the model receives |
| :-- | :-- |
| `str` | That text |
| `dict`, `list`, pydantic model | JSON text. The original data is kept in the result's `data` |
| `TextPart`, `MediaPart` or a list of them | That content |
| [`ToolResult`](#toolresult) | The content in `content` |

When [`ToolError`](#toolerror) is raised, the model receives the error message.

## Tool

```python
Tool(function: Callable, *, name: str | None = None, description: str | Callable, input_schema: dict | None = None, ...)
```

A tool. `@tool` returns a `Tool`. Create one directly to turn a class method into a tool, e.g. `Tool(self.query, name="sql_query", description="Run read-only SQL")`.

Parameters are the same as [tool()](#tool), plus `input_schema`: the JSON Schema of the parameters; when set, it is no longer generated from the function.

### Tool properties

Keys of `annotations`. Tool properties don't affect execution; hooks can use them to handle tool calls.

| Key | Description |
| :-- | :-- |
| `read_only` | Only reads data |
| `destructive` | May delete or overwrite data |
| `open_world` | Results come from web pages or external services |
| `interactive` | Needs user involvement. Set automatically when `client=True` |

## Toolset

```python
Toolset(
    name: str | None = None,
    *,
    tools: Sequence[Tool] = (),
    description: str | None = None,
    requires: Sequence[str] = (),
    hooks: Sequence[Hooks] = (),
)
```

A group of tools; add it to the `tools` parameter of `Agent`.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `name` | `str \| None` | `"toolset"` | Toolset name |
| `tools` | `Sequence[Tool]` | `()` | Tools |
| `description` | `str \| None` | `None` | Toolset description. When used in `Runner`'s `extensions`, the model searches for tools based on it |
| `requires` | `Sequence[str]` | `()` | Resources needed by all tools in the toolset |
| `hooks` | `Sequence[Hooks]` | `()` | Hooks that apply to agents using this toolset |

| Method | Description |
| :-- | :-- |
| `tools(ctx)` | Return the tools. Override in a subclass to return different tools per session |
| `only(*patterns)` | Return a toolset containing only matching tools. Names support the `*` wildcard |
| `exclude(*patterns)` | Return a toolset without matching tools. Names support the `*` wildcard |

When subclassing `Toolset`, you can set the class attribute `needs` (services it depends on); see [Services](services.md).

## ToolResult

```python
ToolResult(*, text: str = ..., content: list = [], data: Any = None, error: str | None = None, error_code: str | None = None)
```

| Field | Type | Description |
| :-- | :-- | :-- |
| `text` | `str` | Text content; equivalent to `content=[TextPart(text=...)]` |
| `content` | `list[TextPart \| MediaPart]` | Content sent to the model |
| `data` | `Any` | Data saved in the session; the model doesn't see it |
| `error` | `str \| None` | Error message |
| `error_code` | `str \| None` | Error code |
| `is_error` | `bool` | Whether it is an error result |

### TextPart

| Field | Type | Description |
| :-- | :-- | :-- |
| `text` | `str` | Text |

### MediaPart

| Field | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `data` | `str` | Required | Base64-encoded content |
| `kind` | `str` | `"image"` | Kind. Values: `image`, `audio`, `video` or `file` |
| `mime` | `str` | `"image/png"` | MIME type |
| `path` | `str \| None` | `None` | Path of the file in the workspace |

`MediaPart.image_bytes(data)` creates a `MediaPart` from image bytes; supports png, jpeg, gif and webp.

## ToolError

```python
ToolError(message: str, *, code: str | None = None, data: Any = None, end_turn: bool = False)
```

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `message` | `str` | Required | Error message, sent to the model |
| `code` | `str \| None` | `None` | Error code |
| `data` | `Any` | `None` | Extra data |
| `end_turn` | `bool` | `False` | Whether to end the turn |

## Context

The `ctx` received by tools and hooks.

### Attributes

| Name | Type | Description |
| :-- | :-- | :-- |
| `session_id` | `str` | Session ID |
| `root_id` | `str` | ID of the top-level session |
| `parent_id` | `str \| None` | ID of the parent session. `None` when not a child session |
| `agent` | `str` | Agent name |
| `session` | `Session` | Current session. See [Session](sessions.md#session) |
| `turn_id` | `str \| None` | Turn ID |
| `turn` | `TurnInfo \| None` | Current turn. `turn.metadata` is the `metadata` passed to `send()` |
| `call` | `ToolCall \| None` | Current tool call. See [ToolCall](hooks.md#toolcall) |
| `tool` | `Tool \| None` | Current tool. `tool.annotations` holds the tool properties |
| `model` | `Model` | Model currently in use |
| `workspace`, `browser`, `computer` | `Any` | Workspace, browser and computer. The tool must list them in `requires`; otherwise use `await ctx.resource()` |
| `tasks` | `TaskControl` | Create and manage child sessions. See [TaskControl](subagents.md#taskcontrol) |

### Methods

| Method | Description |
| :-- | :-- |
| `wait_for(request)` | Issue a [request](requests.md); the turn pauses with `waiting`. Once answered, the tool re-runs from the start and this time returns the answer. In hooks, only usable in `before_tool` and `after_tool` |
| [`step(name, fn)`](#step) | Run an operation that should only run once |
| [`step_key(name)`](#step_key) | Return an idempotency key |
| [`stream(data)`](#stream) | Push data to the frontend |
| [`resource(name, wait)`](#resource) | Return a resource |
| `has_resource(name)` | Return whether the session has this resource |
| `service(kind)` | Return a service. See [Services](services.md) |
| `add_message(message)` | Add a `CustomMessage` to the session |
| `update_message(message_id, ...)` | Update a `CustomMessage`. Same parameters as [update_message()](sessions.md#update_message) |
| `complete_message(message_id, ...)` | Finish an in-progress `CustomMessage`. Same parameters as [complete_message()](sessions.md#complete_message) |
| `end_turn()` | End the turn after the current tool runs |
| [`generate(prompt, ...)`](#generate) | Call the model on its own |

### step()

```python
async def step(name: str, fn: Callable[[], Any]) -> Any
```

Runs `fn`, saves and returns the result. When the tool re-runs because a request was answered, the saved result is returned and `fn` doesn't run again.

| Parameter | Type | Description |
| :-- | :-- | :-- |
| `name` | `str` | Name of the operation, unique within one tool call |
| `fn` | `Callable[[], Any]` | Function to run; may be async. The return value must be JSON-serializable |

### step_key()

```python
def step_key(name: str) -> str
```

Returns an idempotency key, e.g. for calling a payment API. Within one tool call, the same `name` returns the same key, including when the tool re-runs.

### stream()

```python
async def stream(data: Any) -> None
```

Pushes data to the frontend, such as progress. The frontend receives `{"progress": data}` in the `delta` of a `MessageUpdated` event. The data isn't saved and must be JSON-serializable.

### resource()

```python
async def resource(name: str, *, wait: bool = True) -> Any
```

Returns a session resource. Returns `None` if the session doesn't have it.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `name` | `str` | Required | Resource name, e.g. `"workspace"` |
| `wait` | `bool` | `True` | Whether to wait when the resource is temporarily unavailable (e.g. its node is offline). Returns `None` when `False` |

### generate()

```python
async def generate(
    prompt: str | list[Message],
    *,
    system: str = "",
    thinking: str = "off",
    settings: ModelSettings | None = None,
    output: type[BaseModel] | None = None,
    model: Model | None = None,
) -> Any
```

Calls the model on its own, counting usage toward the current turn. Same parameters as the model's [generate()](models.md#generate), plus `model`: the model to use; uses the current model when unset.

## Examples

- [basic/tools.py](../../examples/basic/tools.py): define tools, return results, return errors
- [basic/toolsets.py](../../examples/basic/toolsets.py): toolsets, filtering tools, loading on demand
- [human_in_the_loop/requests.py](../../examples/human_in_the_loop/requests.py): tools run by the frontend
- [workspace/sandbox.py](../../examples/workspace/sandbox.py): use the workspace from a tool
