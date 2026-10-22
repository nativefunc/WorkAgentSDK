"""定时任务：智能体创建定时任务；到期时会话自行开始一轮，输出通过事件获取。"""

import asyncio

from work_agent_sdk import Agent, Runner, Scheduler, ScheduleService
from work_agent_sdk.events import TurnEnded, TurnStarted
from work_agent_sdk.models import Claude

agent = Agent(
    "assistant",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是个人助理。",
    tools=[Scheduler(timezone="Asia/Shanghai")],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()

        result = await session.send("每天早上 9 点提醒我喝水。")
        print(result.text)

        # 应用也可以在代码中为会话创建、暂停、删除任务
        schedules = runner.service(ScheduleService)
        weekly = await schedules.create(
            session.id, "汇总本周的待办", daily="18:00", weekdays=[5], timezone="Asia/Shanghai"
        )
        await schedules.pause(weekly.id)

        jobs = await schedules.list(session.id)
        for job in jobs:
            print("已创建：", job.id, job.prompt, "已暂停" if job.paused else "")

        # 从已保存的最后一个事件之后开始接收
        last_seq = 0
        async for event in session.events(live=False):
            last_seq = event.seq or last_seq

        # 不等到明天 9 点，立即执行一次，看看会话收到什么
        await schedules.run_now(jobs[0].id)  # jobs[0] 是模型创建的任务

        async for event in session.events(after=last_seq):
            if isinstance(event, TurnStarted) and event.source == "schedule":
                print("定时任务开始了一轮")
            if isinstance(event, TurnEnded) and event.result.status != "waiting":
                print("定时任务的输出：", event.result.text)
                break

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
