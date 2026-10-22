"""请求：工具暂停这一轮，等待用户选择、前端执行、外部系统回调，或用户输入密码。

本例在终端中模拟前端：根据请求的类型，向用户提问并提交答复。
"""

import asyncio
import getpass

from pydantic import BaseModel, SecretStr

from work_agent_sdk import Agent, Request, Runner, tool
from work_agent_sdk.models import Claude


class ChooseOption(Request):
    """请用户从几个选项中选一个。字段是展示给用户的内容，Answer 是答复的格式。"""

    question: str
    options: list[str]

    class Answer(BaseModel):
        choice: str


class Password(Request):
    """Answer 中有 SecretStr 字段时，请求为敏感请求，答复不写入会话记录。"""

    prompt: str

    class Answer(BaseModel):
        password: SecretStr


class PaymentConfirmed(Request, answered_by="backend"):
    """由后端答复：等待支付系统回调，用户不需要操作。"""

    order_id: str


@tool(description="请用户从几个方案中选择一个")
async def ask_user(ctx, question: str, options: list[str]) -> str:
    answer = await ctx.wait_for(ChooseOption(question=question, options=options))
    return answer.choice


@tool(description="获取用户当前所在的城市", client=True)
def get_location() -> dict: ...


@tool(description="登录企业邮箱")
async def login_mailbox(ctx, account: str) -> str:
    answer = await ctx.wait_for(Password(prompt=f"请输入 {account} 的密码"))
    ok = len(answer.password.get_secret_value()) > 0
    return "登录成功" if ok else "密码为空"


@tool(description="下单并等待支付完成")
async def checkout(ctx, item: str) -> str:
    order_id = await ctx.step("create", lambda: f"order-{item}")
    await ctx.wait_for(PaymentConfirmed(order_id=order_id))
    return f"订单 {order_id} 已支付"


agent = Agent(
    "assistant",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是个人助理。",
    tools=[ask_user, get_location, login_mailbox, checkout],
)


async def payment_callback(session, order_id: str):
    """模拟支付系统几秒后回调后端：后端找到对应的请求并答复，返回这一轮接下来的结果。"""
    await asyncio.sleep(3)
    for request in await session.pending():
        if request.type == "PaymentConfirmed" and request.data["order_id"] == order_id:
            return await session.answer(request.id, {})


async def ask_in_terminal(session, request):
    """模拟前端：按请求类型向用户提问，返回答复。"""
    if request.type == "ChooseOption":
        for index, option in enumerate(request.data["options"], 1):
            print(f"  {index}. {option}")
        index = int(input(request.data["question"] + " ")) - 1
        return {"choice": request.data["options"][index]}
    if request.type == "ClientTool":
        # data["tool"] 是工具名，data["args"] 是参数；前端执行后把结果作为答复
        return {"city": "杭州"}
    if request.type == "Password":
        return {"password": getpass.getpass(request.data["prompt"] + "：")}
    raise ValueError(f"未处理的请求类型：{request.type}")


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()

        for text in [
            "周末想出去玩，给我几个方案让我选，结合我所在的城市。",
            "登录我的企业邮箱 me@example.com。",
            "帮我买一本《三体》。",
        ]:
            result = await session.send(text)
            while result.status == "waiting":
                request = result.pending[0]
                if request.answered_by == "backend":
                    print("等待支付回调……")
                    result = await payment_callback(session, request.data["order_id"])
                    continue
                answer = await ask_in_terminal(session, request)
                result = await session.answer(request.id, answer)
            print(result.text)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
