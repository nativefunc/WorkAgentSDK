import asyncio

from work_agent_sdk import Agent, Runner, Scheduler, ScheduleService
from work_agent_sdk.events import TurnEnded, TurnStarted
from work_agent_sdk.models import OpenAI

agent = Agent(
    "assistant",
    model=OpenAI("gpt-5"),
    instructions="You are a personal assistant.",
    tools=[Scheduler(timezone="Asia/Shanghai")],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()

        result = await session.send("Remind me to drink water every day at 9 a.m.")
        print(result.text)

        schedules = runner.service(ScheduleService)
        weekly = await schedules.create(
            session.id,
            "Summarize this week's to-dos",
            daily="18:00",
            weekdays=[5],
            timezone="Asia/Shanghai",
        )
        await schedules.pause(weekly.id)

        jobs = await schedules.list(session.id)
        for job in jobs:
            print(job.id, job.prompt, "paused" if job.paused else "")

        saved = [event async for event in session.events(live=False)]
        last_seq = saved[-1].seq

        await schedules.run_now(jobs[0].id)

        turn_id = None
        async for event in session.events(after=last_seq):
            if isinstance(event, TurnStarted) and event.source == "schedule":
                turn_id = event.turn_id
            if isinstance(event, TurnEnded) and event.turn_id == turn_id:
                print(event.result.text)
                break

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
