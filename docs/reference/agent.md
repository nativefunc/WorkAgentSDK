# Agent

## Agent

```python
from work_agent_sdk import Agent
```

```python
Agent(
    name: str,
    *,
    model: Model,
    instructions: str | Callable = "",
    description: str | None = None,
    thinking: str = "off",
    model_settings: ModelSettings | None = None,
    tools: Sequence[Tool | Toolset] = (),
    hooks: Sequence[Hooks] = (),
    output: Any = None,
    max_steps: int | None = None,
)
```

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `name` | `str` | Required | Name. Letters, digits, `_` and `-` only, up to 64 characters |
| `model` | `Model` | Required | Model. See [Models](models.md) |
| `instructions` | `str \| Callable` | `""` | System prompt, or a function that takes `ctx` and returns the system prompt. The function runs before each model call |
| `description` | `str \| None` | `None` | Description of the agent. Required for subagents; the main agent picks subagents by it |
| `thinking` | `str` | `"off"` | Thinking level. Values: `off`, `low`, `medium`, `high` or `max` |
| `model_settings` | `ModelSettings \| None` | `None` | Model parameters. See [ModelSettings](models.md#modelsettings) |
| `tools` | `Sequence[Tool \| Toolset]` | `()` | Tools and toolsets. See [Tools](tools.md) |
| `hooks` | `Sequence[Hooks]` | `()` | Hooks that apply only to this agent. See [Hooks](hooks.md) |
| `output` | `Any` | `None` | Type of the answer, such as a pydantic model. When set, the answer's data is in `TurnResult.data` |
| `max_steps` | `int \| None` | `None` | Maximum number of model calls per turn. When exceeded, the turn ends with `error` |

## Examples

- [basic/hello.py](../../examples/basic/hello.py): create an agent, multi-turn conversation
- [basic/structured_output.py](../../examples/basic/structured_output.py): structured output
