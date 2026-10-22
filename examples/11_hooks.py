"""钩子：在一轮的各个阶段检查、修改或拒绝。

- before_turn：拒绝不合规的消息
- before_model：短问题改用便宜的模型
- before_tool / after_tool：拦截危险调用，记录审计日志
- before_turn_end：回答不满足要求时让模型继续
- on_model_error：模型调用失败时换用备用模型
"""

import asyncio

from work_agent_sdk import Agent, Continue, Deny, Hooks, Runner, only_tools, tool
from work_agent_sdk.models import Claude

haiku = Claude("claude-haiku-4-5")
backup = Claude("claude-sonnet-4-5", id="backup")


@tool(description="在指定数据库上执行 SQL")
async def run_sql(database: str, sql: str) -> str:
    return f"已在 {database} 执行：{sql}"


class Guard(Hooks):
    async def before_turn(self, ctx, message):
        if "身份证号" in message.text:
            return Deny("不能处理包含身份证号的请求")
        return None

    async def before_model(self, ctx, request):
        if len(request.messages) <= 1 and len(request.messages[-1].text) < 20:
            return request.model_copy(update={"model": haiku})
        return None

    @only_tools("run_sql")
    async def before_tool(self, ctx, call):
        sql = call.args["sql"].lstrip().lower()
        if call.args["database"] == "prod" and not sql.startswith("select"):
            return Deny("生产库只允许执行查询")
        return None

    @only_tools("run_sql")
    async def after_tool(self, ctx, call, result):
        print(f"[审计] {call.args} -> {'失败' if result.error else '成功'}")

    async def before_turn_end(self, ctx, message):
        if "SQL" not in message.text:
            return Continue("请在回答末尾列出你执行过的 SQL。")
        return None

    async def on_model_error(self, ctx, request, error):
        if error.code in ("overloaded", "rate_limit"):
            return request.model_copy(update={"model": backup})
        return None


agent = Agent("dba", model=Claude("claude-sonnet-4-5"), instructions="你是数据库助手。", tools=[run_sql])


async def main():
    # 放在 Runner(hooks=...) 中的钩子对所有 Agent 生效；也可以放在 Agent(hooks=...) 中
    async with Runner(agents=[agent], hooks=[Guard()]) as runner:
        session = await runner.new_session()

        result = await session.send("查一下张三的身份证号。")
        print(result.status, result.error.message)

        result = await session.send("在 prod 库删除 30 天前的日志，再统计 users 表的行数。")
        print(result.text)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
