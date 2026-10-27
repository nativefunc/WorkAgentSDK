import asyncio
import os

from work_agent_sdk import MCP, SRT, Agent, Runner, Workspace
from work_agent_sdk.models import OpenAI

docs = MCP(
    "docs",
    url=os.environ["DOCS_MCP_URL"],
    headers={"Authorization": "Bearer ${DOCS_MCP_TOKEN}"},
    description="Internal company documents",
)

memory = MCP(
    "memory",
    command="npx",
    args=["-y", "@modelcontextprotocol/server-memory"],
)

files = MCP(
    "files",
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", "."],
    runs_on="workspace",
)

agent = Agent(
    "assistant",
    model=OpenAI("gpt-5"),
    instructions="You are an assistant. Use the MCP server tools when needed.",
    tools=[docs, memory, files],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(
            workspace=Workspace("~/work-agent-demo", sandbox=SRT()),
        )
        result = await session.send("Which tools can you use? List their names and what they do.")
        print(result.text)
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
