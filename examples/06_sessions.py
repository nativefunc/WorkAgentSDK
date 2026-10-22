"""会话：保存后重新打开、读取记录、加入应用自己的消息、消息排队、撤回和复制。"""

import asyncio

from work_agent_sdk import Agent, CustomMessage, Runner
from work_agent_sdk.models import Claude

agent = Agent(
    "support",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是网店客服。",
)


async def first_run() -> str:
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(metadata={"user_id": "u_1024"})
        result = await session.send("我想买一台 27 寸显示器，预算 2000 元。")
        print(result.text)
        return session.id


async def second_run(session_id: str):
    # 程序重启后，按 id 打开原来的会话
    async with Runner(agents=[agent]) as runner:
        session = await runner.session(session_id)
        print("metadata：", (await session.info()).metadata)

        # 应用自己的事件作为消息加入会话。add_message 不开始新的一轮，模型下次调用时看到它
        await session.add_message(
            CustomMessage(
                "coupon.issued",
                data={"code": "SAVE200", "amount": 200},
                for_model="系统已给该用户发放一张 200 元优惠券 SAVE200。",
            )
        )

        result = await session.send("用券之后预算能多出多少？")
        print(result.text)

        # 一轮进行中发送的消息会排队；队列中 priority 大的先处理
        handles = [
            session.send("推荐一款。"),
            session.send("支持七天无理由退货吗？"),
            session.send("顺便问下发票怎么开？", priority=10),
        ]
        for handle in handles:
            await handle.queued()
        print("排队中：", [item.message.text for item in await session.queue.list()])
        for handle in handles:
            print((await handle).text)

        # 读取记录，撤回最后一条用户消息及之后的内容
        messages = await session.history()
        last_user = [m for m in messages if m.role == "user"][-1]
        hidden = await session.rewind(last_user.id)
        print("撤回了", len(hidden), "条消息")

        # 从第一条用户消息之前复制出一个新会话，原会话不变
        first_user = next(m for m in messages if m.role == "user")
        copy = await session.fork(first_user.id)
        print("复制出的会话：", copy.id)

        print("累计用量：", await session.usage())
        await session.close()
        await copy.close()


async def main():
    session_id = await first_run()
    await second_run(session_id)


if __name__ == "__main__":
    asyncio.run(main())
