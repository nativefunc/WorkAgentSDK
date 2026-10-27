# Examples

Before running the examples, install the SDK and the OpenAI dependency from the source root, and set your API key:

```bash
pip install . openai
export OPENAI_API_KEY=...
```

The README.md in each directory explains the setup and how to run that directory's examples.

## Basics

| Example | Contents |
| :-- | :-- |
| [basic/hello.py](basic/hello.py) | Send messages, multi-turn conversation |
| [basic/tools.py](basic/tools.py) | Define tools: return data, return errors, hand full data to the frontend |
| [basic/toolsets.py](basic/toolsets.py) | Toolsets: different tools per session, filter tools, load tools on demand |
| [basic/structured_output.py](basic/structured_output.py) | Structured output |
| [basic/streaming.py](basic/streaming.py) | Streaming output, showing tool calls |
| [basic/models.py](basic/models.py) | Thinking level, model parameters, per-session API keys, switching models, calling the model on its own |
| [basic/providers.py](basic/providers.py) | Integrate OpenAI, Claude, Qwen, DeepSeek, Zhipu |
| [basic/custom_model.py](basic/custom_model.py) | Custom model; runs without an API key |

## Sessions

| Example | Contents |
| :-- | :-- |
| [sessions/sessions.py](sessions/sessions.py) | Reopen a session, add messages, message queue, rewind, fork |
| [sessions/event_stream.py](sessions/event_stream.py) | All events in a turn, converting events into what the frontend displays |
| [sessions/reconnect.py](sessions/reconnect.py) | Resubscribe after a disconnect using `after` and `snapshot` |

## Human in the loop

| Example | Contents |
| :-- | :-- |
| [human_in_the_loop/approval.py](human_in_the_loop/approval.py) | Ask the user to confirm before deploying |
| [human_in_the_loop/requests.py](human_in_the_loop/requests.py) | Custom requests, tools run by the frontend, requests answered by the backend, entering a password |
| [human_in_the_loop/hooks.py](human_in_the_loop/hooks.py) | Hooks: answer commands without the model, pick the model per user plan, block writes to production, audit and truncate tool results, make the model verify its changes, switch to a fallback model |

## Environments

| Example | Contents |
| :-- | :-- |
| [workspace/workspace.py](workspace/workspace.py) | The agent writes and runs code in the workspace; the app reads and writes files, runs commands and starts background processes |
| [workspace/sandbox.py](workspace/sandbox.py) | Configure the sandbox, allow new domains, ask the user to confirm before running commands outside the sandbox |
| [browser/browser.py](browser/browser.py) | Access rules, keeping sign-in state, operating the browser from code |
| [browser/cdp.py](browser/cdp.py) | Connect to a running Chrome and use its sign-in state |
| [computer/computer.py](computer/computer.py) | Operate desktop apps, handle app authorization and takeover requests |
| [nodes](nodes) | Backend connects to a device and runs commands in the device's workspace |

## Extensions

| Example | Contents |
| :-- | :-- |
| [subagents/subagents.py](subagents/subagents.py) | Foreground, background and on-demand subagents |
| [subagents/tasks.py](subagents/tasks.py) | Create child sessions from tools and from the app |
| [mcp/mcp.py](mcp/mcp.py) | Connect to a remote server, start a local server, start a server in the workspace |
| [skills](skills) | Load skills on demand, run scripts in a skill, pick the skills used for a turn |
| [schedules/schedules.py](schedules/schedules.py) | Agent and app create scheduled tasks and get the results |

## Advanced

| Example | Contents |
| :-- | :-- |
| [advanced/custom_service](advanced/custom_service) | Custom service: provide a SQLite database to sessions, check inventory in the background and notify the session |
| [advanced/isolated_env](advanced/isolated_env) | Run the device program in a Docker container; the agent works inside the container |
| [advanced/shared_folder](advanced/shared_folder) | Workspace, browser and computer on three machines, exchanging files through a shared folder |

## Web apps

| Example | Contents |
| :-- | :-- |
| [apps/web_backend](apps/web_backend) | Chat API, pushing events over SSE, approving in a web page, with a frontend page |
| [apps/webhook](apps/webhook) | Add notifications from external systems to a session, using CI build notifications as an example |
| [apps/device_connect](apps/device_connect) | Device connects to the backend: issue device tokens; the agent runs commands in the device's workspace |
| [apps/mcp_oauth](apps/mcp_oauth) | OAuth authorization for MCP servers |
| [apps/takeover](apps/takeover) | User takeover: push live browser or screen frames and forward the user's actions |

## Showcase projects

| Example | Contents |
| :-- | :-- |
| [showcase/openmuse](showcase/openmuse) | Personal AI assistant |