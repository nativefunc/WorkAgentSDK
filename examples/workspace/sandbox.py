import asyncio

from work_agent_sdk import (
    SRT,
    Agent,
    Approval,
    Deny,
    Hooks,
    Runner,
    Shell,
    Workspace,
    only_tools,
    tool,
)
from work_agent_sdk.models import OpenAI

sandbox = SRT(
    network=["pypi.org", "files.pythonhosted.org"],
    write=["../pip-cache"],
    protect=[".env", ".github/"],
    deny_read=["~/.ssh", "~/.aws", "~/.config", "~/secrets"],
)


@tool(
    description="Request access to a domain the sandbox doesn't allow. Once the user approves, later commands can access that domain.",
    requires=["workspace"],
)
async def request_network(ctx, domain: str, reason: str) -> str:
    answer = await ctx.wait_for(Approval(title=f"Allow access to {domain}?", detail=reason))
    if not answer.approved:
        return f"The user didn't approve access to {domain}"

    sandbox = await ctx.workspace.get_sandbox()
    if domain not in sandbox.network:
        sandbox.network.append(domain)
        await ctx.workspace.set_sandbox(sandbox)
    return f"Access to {domain} allowed"


class ApproveUnsandboxed(Hooks):
    @only_tools("shell")
    async def before_tool(self, ctx, call):
        if not call.args.get("unsandboxed"):
            return None
        answer = await ctx.wait_for(
            Approval(
                title=call.args.get("unsandboxed_reason") or "Run a command outside the sandbox",
                detail=call.args["command"],
            )
        )
        return None if answer.approved else Deny("The user didn't approve running outside the sandbox")


agent = Agent(
    "dev",
    model=OpenAI("gpt-5"),
    instructions="You are a development assistant.",
    tools=[Shell(allow_unsandboxed=True), request_network],
    hooks=[ApproveUnsandboxed()],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(
            workspace=Workspace("~/work-agent-demo", sandbox=sandbox),
        )

        result = await session.send("Install requests, then use it to fetch https://example.com and print the status code.")
        while result.status == "waiting":
            request = result.pending[0]
            reply = input(f"{request.data['title']}\n{request.data['detail']}\nApprove? [y/N] ")
            result = await session.answer(request.id, {"approved": reply.strip().lower() == "y"})
        print(result.text)

        workspace = await session.workspace()
        run = await workspace.run("curl -sI https://example.com | head -1", unsandboxed=True)
        print(run.stdout)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
