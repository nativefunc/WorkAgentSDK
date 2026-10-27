import asyncio

from work_agent_sdk import (
    SRT,
    Agent,
    Browser,
    BrowserPolicy,
    BrowserUse,
    Computer,
    ComputerUse,
    Device,
    Runner,
    SharedFolder,
    Shell,
    Workspace,
)
from work_agent_sdk.models import OpenAI

agent = Agent(
    "analyst",
    model=OpenAI("gpt-5"),
    instructions="You are a data analysis assistant. Use the browser to work with internal company systems, process data in the workspace, and present results on the user's computer.",
    tools=[Shell(), BrowserUse(), ComputerUse()],
)

nodes = [
    Device(
        "dev-server",
        connect="ws://dev-server.internal:7443",
        token="${DEV_SERVER_TOKEN}",
    ),
    Device(
        "browser-host",
        connect="ws://browser-host.internal:7443",
        token="${BROWSER_HOST_TOKEN}",
    ),
    Device(
        "office-pc",
        connect="ws://office-pc.internal:7443",
        token="${OFFICE_PC_TOKEN}",
    ),
]

team = SharedFolder(
    "team",
    {
        "dev-server": "/mnt/team",
        "browser-host": "/data/team",
        "office-pc": "/Volumes/team",
    },
)

workspace = Workspace(
    "~/analysis",
    node="dev-server",
    sandbox=SRT(read=["/mnt/team/downloads"], write=["/mnt/team/reports"]),
)

browser = Browser(
    node="browser-host",
    download_dir="/data/team/downloads",
    policy=BrowserPolicy.standard(
        allow=["reports.example.internal"],
        private=["reports.example.internal"],
        enable=["file_upload"],
    ),
)

computer = Computer(node="office-pc", description="The user's office computer, with Numbers installed")

TASK = """\
1. Download last month's sales detail CSV from https://reports.example.internal.
2. In the workspace, total sales by region, generate an xlsx spreadsheet, and save it to the reports directory of the shared folder.
3. Open this spreadsheet in Numbers on the user's computer.
4. Upload this spreadsheet to the "Monthly Summary" page of the reporting system.
"""


def ask_in_terminal(request) -> dict:
    if request.type == "Approval":
        paths = ", ".join(request.data["detail"]["args"]["paths"])
        reply = input(f"{request.data['title']}\nFiles: {paths}\nAllow? [y/N] ")
        return {"approved": reply.strip().lower() == "y"}
    if request.type == "AppAccess":
        apps = ", ".join(app["name"] for app in request.data["apps"])
        reply = input(f"Allow operating {apps}? Reason: {request.data['reason']} [y/N] ")
        return {"approved": reply.strip().lower() == "y"}
    input(f"Please handle this manually: {request.data['reason']}. Press Enter when done.")
    return {"done": True}


async def main():
    async with Runner(agents=[agent], nodes=nodes, shared_folders=[team]) as runner:
        session = await runner.new_session(
            workspace=workspace,
            browser=browser,
            computer=computer,
        )

        result = await session.send(TASK)
        while result.status == "waiting":
            request = result.pending[0]
            result = await session.answer(request.id, ask_in_terminal(request))

        print(result.text)
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
