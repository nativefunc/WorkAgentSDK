# Workspace

| Example | Contents |
| :-- | :-- |
| [workspace.py](workspace.py) | The agent writes and runs code in the workspace; the app reads and writes files, runs commands and starts background processes |
| [sandbox.py](sandbox.py) | Configure the sandbox, allow new domains, ask the user to confirm before running commands outside the sandbox |

## Setup

Install srt:

| OS | Command |
| :-- | :-- |
| macOS | `npm install -g @anthropic-ai/sandbox-runtime` |
| Linux | `npm install -g @anthropic-ai/sandbox-runtime`, then `sudo apt install bubblewrap socat ripgrep` |

## Run

Run from this directory, e.g.:

```bash
python workspace.py
```

The example workspace is `~/work-agent-demo`. `sandbox.py` asks the user to confirm in the terminal.
