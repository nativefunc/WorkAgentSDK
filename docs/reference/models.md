# Models

```python
from work_agent_sdk.models import Claude, Model, ModelSettings, OpenAI, OpenAICompatible, Qwen
```

## Built-in model classes

| Class | Dependency | Environment variable read by default |
| :-- | :-- | :-- |
| `OpenAI` | `openai` | `OPENAI_API_KEY` |
| `Claude` | `anthropic` | `ANTHROPIC_API_KEY` |
| `Qwen` | `dashscope` | `DASHSCOPE_API_KEY` |
| `OpenAICompatible` | `openai` | None; set it with `api_key`. For services compatible with the OpenAI Chat Completions API; set the address with `base_url` |

### Common parameters

All model classes take the following parameters.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `name` | `str` | Required | Model name sent to the model provider |
| `id` | `str \| None` | `name` | Model ID. Used when switching models; see [update()](sessions.md#update) |
| `api_key` | `str \| Callable \| None` | `None` | API key; supports `${ENV_VAR}`. Can also be a function that takes `ctx` and returns the key; `ctx` is `None` when the model is called outside a session |
| `base_url` | `str \| None` | `None` | Address of the model provider |
| `headers` | `dict \| Callable \| None` | `None` | Extra request headers. Supports `${ENV_VAR}` |
| `timeout` | `float` | `600` | Request timeout (seconds) |
| `client` | `Any` | `None` | The model provider's SDK client. When set, `api_key` and `base_url` cannot be set. Not available for `Qwen` |
| `input_types` | `Iterable[str]` | `("text", "image")` | Input types the model supports. Values: `text`, `image`, `audio` or `video` |
| `max_output_tokens` | `int \| None` | `None` | Maximum output tokens |
| `structured_output` | `bool` | `False` | Whether to use the model provider's structured output |
| `max_retries` | `int` | `3` | Maximum number of retries. Retries on error codes `rate_limit`, `overloaded`, `server`, `network` or `timeout` |
| `retry_delay` | `float` | `1.0` | Wait before the first retry (seconds) |
| `thinking_levels` | `Iterable[str] \| None` | `None` | Thinking levels the model supports. All are supported when unset |
| `native_tools` | `Iterable[str]` | `()` | Toolsets that use the model provider's built-in tools. Values: `computer` or `browser`. Defaults to `("computer", "browser")` for `Claude` |
| `native_tool_search` | `bool` | `True` | Whether to use the model provider's built-in tool search. See `Runner`'s [`extensions`](runner.md#runner) |
| `max_image_edge` | `int` | `2048` | Longest edge of images sent to the model (pixels) |
| `max_image_bytes` | `int` | `5000000` | Maximum size of a single image sent to the model, in bytes (after base64 encoding) |
| `screen_coordinates` | `tuple[int, int] \| None` | `None` | Coordinate system the model uses for screen coordinates, e.g. `(1000, 1000)`. Screenshot pixels when unset. Defaults to `(1000, 1000)` for `Qwen` |

### OpenAI parameters

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `api` | `str` | `"responses"` | API to use. Values: `responses` or `chat` |
| `reasoning_summary` | `str` | `"auto"` | Detail level of the reasoning summary. Values: `auto`, `concise` or `detailed` |

### Claude parameters

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `thinking_mode` | `str` | `"budget"` | Thinking mode. Values: `budget`, `adaptive` or `none` |
| `default_max_tokens` | `int` | `8192` | Value used when maximum output tokens is not set |
| `cache` | `bool` | `True` | Whether to use prompt caching |

### OpenAICompatible parameters

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `thinking_format` | `str` | `"none"` | Request format used to toggle thinking. Values: `openai`, `enable_thinking`, `thinking_type`, `openrouter` or `none` |
| `reasoning_in_history` | `bool` | `False` | Whether to send the thinking content of past answers to the model |
| `max_tokens_field` | `str` | `"max_tokens"` | Field name used for maximum output tokens |
| `stream_usage` | `bool` | `True` | Whether to request usage in streaming responses |

### generate()

```python
async def generate(
    prompt: str | list[Message],
    *,
    system: str = "",
    thinking: str = "off",
    settings: ModelSettings | None = None,
    output: type[BaseModel] | None = None,
) -> Any
```

A method on the model. Calls the model once on its own and returns the answer text; when `output` is set, returns an object of the `output` type. To call it from a tool and count it toward the turn's usage, use [`ctx.generate()`](tools.md#generate).

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `prompt` | `str \| list[Message]` | Required | Prompt or messages |
| `system` | `str` | `""` | System prompt |
| `thinking` | `str` | `"off"` | Thinking level. Values: `off`, `low`, `medium`, `high` or `max` |
| `settings` | `ModelSettings \| None` | `None` | Model parameters |
| `output` | `type[BaseModel] \| None` | `None` | Return type. The model must set `structured_output=True` |

## ModelSettings

```python
ModelSettings(*, temperature=None, top_p=None, max_tokens=None, stop=None, seed=None, thinking_budget=None, extra_body={}, extra_headers={})
```

Model parameters, passed to `Agent`'s `model_settings` or `generate()`'s `settings`.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `temperature` | `float \| None` | `None` | Sampling temperature |
| `top_p` | `float \| None` | `None` | Nucleus sampling probability |
| `max_tokens` | `int \| None` | `None` | Maximum output tokens |
| `stop` | `list[str] \| None` | `None` | Stop sequences |
| `seed` | `int \| None` | `None` | Random seed |
| `thinking_budget` | `int \| None` | `None` | Thinking tokens. Determined by the thinking level when unset |
| `extra_body` | `dict` | `{}` | Parameters merged into the request body |
| `extra_headers` | `dict[str, str]` | `{}` | Extra request headers |

## Model

To integrate another model provider, subclass `Model` and implement `stream()`.

```python
async def stream(self, request: ModelRequest) -> AsyncIterator[Delta]
```

For `request` see [ModelRequest](hooks.md#modelrequest). `stream()` yields the model's output in chunks and raises [`ModelError`](hooks.md#modelerror) when the call fails.

| Output | Fields | Description |
| :-- | :-- | :-- |
| `TextDelta` | `text` | Answer text |
| `ThinkingDelta` | `text`, `signature`, `redacted` | Thinking content |
| `ToolCallDelta` | `index`, `id`, `name`, `args` | Tool call. Chunks with the same `index` are merged into one call; `args` can be given as string chunks or as a single dict |
| `Finish` | `stop_reason`, `usage` | End. `stop_reason` is why it ended, e.g. `stop`, `length`; `usage` is the usage |

## Examples

- [basic/models.py](../../examples/basic/models.py): thinking levels, model parameters, per-session keys, switching models, calling the model on its own
- [basic/providers.py](../../examples/basic/providers.py): integrating various model providers
- [basic/custom_model.py](../../examples/basic/custom_model.py): integrating another model provider
