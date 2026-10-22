"""沙箱：调整命令能读写的路径和能访问的网络；模型申请在沙箱外执行命令时，先请用户批准。

运行前需要安装 srt：npm install -g @anthropic-ai/sandbox-runtime
"""

import asyncio

from work_agent_sdk import SRT, Agent, Approval, Deny, Hooks, Runner, Shell, Workspace, only_tools
from work_agent_sdk.models import Claude

sandbox = SRT(
    network=["pypi.org", "files.pythonhosted.org"],  # 允许访问的域名，其他一律禁止
    write=["../pip-cache"],  # 工作区之外额外允许写入的目录，相对于工作区
    protect=[".env", ".github/"],  # 工作区之内禁止写入的路径
    deny_read=["~/.ssh", "~/.aws", "~/.config", "~/secrets"],  # 禁止读取的路径，替换默认列表
)


class ApproveUnsandboxed(Hooks):
    """Shell(allow_unsandboxed=True) 时，模型可以申请在沙箱外执行命令。框架本身不审批，这里请用户确认。"""

    @only_tools("shell")
    async def before_tool(self, ctx, call):
        if not call.args.get("unsandboxed"):
            return None
        answer = await ctx.wait_for(
            Approval(title=call.args.get("unsandboxed_reason") or "在沙箱外执行命令", detail=call.args["command"])
        )
        return None if answer.approved else Deny("用户未批准在沙箱外执行")


agent = Agent(
    "dev",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是开发助手。",
    tools=[Shell(allow_unsandboxed=True)],
    hooks=[ApproveUnsandboxed()],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(workspace=Workspace("~/work-agent-demo", sandbox=sandbox))

        result = await session.send("安装 requests，然后用它访问 https://example.com 并打印状态码。")
        while result.status == "waiting":
            request = result.pending[0]
            reply = input(f"{request.data['title']}\n  {request.data['detail']}\n批准？[y/N] ")
            result = await session.answer(request.id, {"approved": reply.strip().lower() == "y"})
        print(result.text)

        # 应用在代码中可以直接在沙箱外执行命令，不经过审批
        workspace = await session.workspace()
        run = await workspace.run("curl -sI https://example.com | head -1", unsandboxed=True)
        print(run.stdout)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
