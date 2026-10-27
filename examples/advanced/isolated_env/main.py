import asyncio
import secrets
from pathlib import Path

from work_agent_sdk import SRT, Agent, Device, Runner, Shell, Workspace
from work_agent_sdk.models import OpenAI

IMAGE = "work-agent-device"
AUDIT_DIR = Path("audit-logs").resolve()

agent = Agent(
    "coder",
    model=OpenAI("gpt-5"),
    instructions="You work in a dedicated container and can install any software you need.",
    tools=[Shell()],
)


async def docker(*args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode())
    return stdout.decode().strip()


async def start_container(name: str) -> Device:
    token = secrets.token_urlsafe(32)
    await docker(
        "run",
        "-d",
        "--rm",
        "--name",
        name,
        "-p",
        "127.0.0.1::7000",
        "-v",
        f"{AUDIT_DIR / name}:/var/log/work-agent",
        "-e",
        f"DEVICE_NAME={name}",
        "-e",
        f"DEVICE_TOKEN={token}",
        IMAGE,
    )
    address = (await docker("port", name, "7000")).splitlines()[0]
    return Device(name, connect=f"ws://{address}", token=token, wait=60)


async def main():
    async with Runner(agents=[agent]) as runner:
        name = f"sandbox-{secrets.token_hex(4)}"
        runner.nodes.add(await start_container(name))

        try:
            session = await runner.new_session(
                workspace=Workspace(
                    "/workspace",
                    node=name,
                    sandbox=SRT(network=["pypi.org", "files.pythonhosted.org"]),
                ),
            )
            result = await session.send("Create a Python virtual environment in the workspace, install cowsay, then use it to say hello.")
            print(result.text)
            await session.close()
        finally:
            await runner.nodes.remove(name)
            await docker("rm", "-f", name)


if __name__ == "__main__":
    asyncio.run(main())
