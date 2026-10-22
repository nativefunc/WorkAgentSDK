"""MCP：把 MCP 服务的工具提供给智能体。

- 远程服务：用 url 连接，请求头中的 ${变量名} 从环境变量读取
- 本地服务：用 command 启动，默认在后端机器上运行，不受沙箱限制
- 在工作区中启动：每个会话各启动一个，受工作区沙箱限制

运行前：
    export DOCS_MCP_URL=https://mcp.example.com/mcp
    export DOCS_MCP_TOKEN=...
    本地服务需要 Node.js（npx）
"""

import asyncio
import os

from work_agent_sdk import MCP, SRT, Agent, Runner, Workspace
from work_agent_sdk.models import Claude

docs = MCP(
    "docs",
    url=os.environ["DOCS_MCP_URL"],
    headers={"Authorization": "Bearer ${DOCS_MCP_TOKEN}"},
    description="公司内部文档",
)

# 模型看到的工具名为 mcp__memory__<工具名>
memory = MCP("memory", command="npx", args=["-y", "@modelcontextprotocol/server-memory"])

# 在会话的工作区中启动，服务只能访问工作区中的文件；会话没有工作区时，模型看不到这些工具
files = MCP(
    "files",
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", "."],
    runs_on="workspace",
)

agent = Agent(
    "assistant",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是一名助手，需要时使用 MCP 服务提供的工具。",
    tools=[docs, memory, files],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(workspace=Workspace("~/work-agent-demo", sandbox=SRT()))
        result = await session.send("你能用哪些工具？列出名称和用途。")
        print(result.text)
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
