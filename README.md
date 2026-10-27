<div align="center">

# Work Agent SDK

[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-2EA44F)](LICENSE)
[![Models](https://img.shields.io/badge/models-OpenAI_%7C_Claude_%7C_Qwen-D97757)](docs/reference/models.md)
[![MCP](https://img.shields.io/badge/MCP-supported-6E56CF?logo=modelcontextprotocol&logoColor=white)](docs/reference/mcp.md)
[![Agent Skills](https://img.shields.io/badge/Agent_Skills-supported-6E56CF)](docs/reference/skills.md)

</div>

Work Agent SDK is a Python framework for building agents.

## Installation

Requires Python 3.11 or later.

```bash
pip install .
```

## Quick start

```bash
pip install openai
export OPENAI_API_KEY=...
```

```python
import asyncio

from work_agent_sdk import Agent, Runner
from work_agent_sdk.models import OpenAI

agent = Agent("assistant", model=OpenAI("gpt-5"), instructions="You are an assistant.")


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()
        result = await session.send("Describe Python in one sentence.")
        print(result.text)


asyncio.run(main())
```

## Showcase: OpenMuse

[OpenMuse](examples/showcase/openmuse) is a personal assistant app built on Work Agent SDK, with a backend, a Flutter app and a cloud desktop that runs in Docker.

<table>
  <tr>
    <td align="center" width="25%"><img src="examples/showcase/openmuse/screenshots/01-home.png" width="200" alt="Start a chat"><br><sub>Start a chat</sub></td>
    <td align="center" width="25%"><img src="examples/showcase/openmuse/screenshots/02-browser-chat.png" width="200" alt="The agent opens the browser"><br><sub>The agent opens the browser</sub></td>
    <td align="center" width="25%"><img src="examples/showcase/openmuse/screenshots/03-browser-takeover.png" width="200" alt="Watch live and take over"><br><sub>Watch live and take over</sub></td>
    <td align="center" width="25%"><img src="examples/showcase/openmuse/screenshots/04-app-access.png" width="200" alt="Approve the apps it can use"><br><sub>Approve the apps it can use</sub></td>
  </tr>
  <tr>
    <td align="center" width="25%"><img src="examples/showcase/openmuse/screenshots/05-computer-takeover.png" width="200" alt="Take control of the desktop"><br><sub>Take control of the desktop</sub></td>
    <td align="center" width="25%"><img src="examples/showcase/openmuse/screenshots/06-activity.png" width="200" alt="Track tasks and routines"><br><sub>Track tasks and routines</sub></td>
    <td align="center" width="25%"><img src="examples/showcase/openmuse/screenshots/07-profile.png" width="200" alt="Connect your computer"><br><sub>Connect your computer</sub></td>
  </tr>
</table>

## Documentation

- [Examples](examples/README.md): how to use each feature
- [API reference](docs/reference/index.md): classes, parameters, attributes and methods

## License

[Apache-2.0](LICENSE)
