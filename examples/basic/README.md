# Basics

| Example | Contents |
| :-- | :-- |
| [hello.py](hello.py) | Send messages, multi-turn conversation |
| [tools.py](tools.py) | Define tools: return data, return errors, hand full data to the frontend |
| [toolsets.py](toolsets.py) | Toolsets: different tools per session, filter tools, load tools on demand |
| [structured_output.py](structured_output.py) | Structured output |
| [streaming.py](streaming.py) | Streaming output, showing tool calls |
| [models.py](models.py) | Thinking level, model parameters, per-session API keys, switching models, calling the model on its own |
| [providers.py](providers.py) | Integrate OpenAI, Claude, Qwen, DeepSeek, Zhipu |
| [custom_model.py](custom_model.py) | Custom model |

## Run

Run from this directory, e.g.:

```bash
python hello.py
```

For [providers.py](providers.py), pass the provider name when running and set the matching API key:

| Provider | Command | Environment variable | Install |
| :-- | :-- | :-- | :-- |
| OpenAI | `python providers.py openai` | `OPENAI_API_KEY` | `pip install openai` |
| Claude | `python providers.py claude` | `ANTHROPIC_API_KEY` | `pip install anthropic` |
| Qwen | `python providers.py qwen` | `DASHSCOPE_API_KEY` | `pip install dashscope` |
| DeepSeek | `python providers.py deepseek` | `DEEPSEEK_API_KEY` | `pip install openai` |
| Zhipu | `python providers.py glm` | `ZHIPU_API_KEY` | `pip install openai` |
