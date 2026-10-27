import asyncio
import getpass

from pydantic import BaseModel, SecretStr

from work_agent_sdk import Agent, Request, Runner, tool
from work_agent_sdk.models import OpenAI


class ChooseOption(Request):
    question: str
    options: list[str]

    class Answer(BaseModel):
        choice: str


class Password(Request):
    prompt: str

    class Answer(BaseModel):
        password: SecretStr


class PaymentConfirmed(Request, answered_by="backend"):
    order_id: str


@tool(description="Ask the user to choose one of several options")
async def ask_user(ctx, question: str, options: list[str]) -> str:
    answer = await ctx.wait_for(ChooseOption(question=question, options=options))
    return answer.choice


@tool(description="Get the user's city", client=True)
def get_location() -> dict: ...


@tool(description="Sign in to the company email")
async def login_mailbox(ctx, account: str) -> str:
    answer = await ctx.wait_for(Password(prompt=f"Enter the password for {account}"))
    return "Signed in" if answer.password.get_secret_value() else "Password is empty"


@tool(description="Place an order and wait for payment to complete")
async def checkout(ctx, item: str) -> str:
    order_id = await ctx.step("create_order", lambda: f"order-{item}")
    await ctx.wait_for(PaymentConfirmed(order_id=order_id))
    return f"Order {order_id} paid"


agent = Agent(
    "assistant",
    model=OpenAI("gpt-5"),
    instructions="You are a personal assistant.",
    tools=[ask_user, get_location, login_mailbox, checkout],
)


async def payment_callback(session, order_id: str):
    await asyncio.sleep(3)
    for request in await session.pending():
        if request.type == "PaymentConfirmed" and request.data["order_id"] == order_id:
            return await session.answer(request.id, {})


def ask_in_terminal(request) -> dict:
    if request.type == "ChooseOption":
        for index, option in enumerate(request.data["options"], 1):
            print(f"{index}. {option}")
        index = int(input(request.data["question"] + " ")) - 1
        return {"choice": request.data["options"][index]}
    if request.type == "ClientTool":
        return {"city": "Hangzhou"}
    if request.type == "Password":
        return {"password": getpass.getpass(request.data["prompt"] + ": ")}
    raise ValueError(f"Unhandled request: {request.type}")


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()

        for text in [
            "I want to go out this weekend. Give me a few options to choose from based on my city.",
            "Sign in to my company email me@example.com.",
            "Buy me a copy of The Three-Body Problem.",
        ]:
            result = await session.send(text)
            while result.status == "waiting":
                request = result.pending[0]
                if request.answered_by == "backend":
                    print("Waiting for the payment callback")
                    result = await payment_callback(session, request.data["order_id"])
                else:
                    result = await session.answer(request.id, ask_in_terminal(request))
            print(result.text)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
