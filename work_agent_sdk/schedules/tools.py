from __future__ import annotations

import datetime
import time
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from pydantic import Field

import work_agent_sdk.strings.schedules as strings
from work_agent_sdk.core.errors import ToolError
from work_agent_sdk.core.tool import Context, Tool, Toolset
from work_agent_sdk.schedules.service import ScheduleService
from work_agent_sdk.schedules.store import ScheduleRecord


class Scheduler(Toolset):
    """定时任务工具集。模型给出的时间按 timezone 解释；会话关闭时，其定时任务一并删除。"""

    name = "scheduler"
    description = "创建和管理定时任务"
    needs = (ScheduleService,)

    def __init__(self, *, timezone: str = "UTC", max_jobs_per_session: int = 20) -> None:
        super().__init__()
        ZoneInfo(timezone)
        self.timezone = timezone
        self.max_jobs_per_session = max_jobs_per_session
        self._tools = [
            Tool(
                self._schedule_task,
                name="schedule_task",
                description=strings.SCHEDULE_DESCRIPTION.format(timezone=timezone),
            ),
            Tool(
                self._list_scheduled_tasks,
                name="list_scheduled_tasks",
                description=strings.LIST_DESCRIPTION,
                annotations={"read_only": True},
            ),
            Tool(self._cancel_scheduled_task, name="cancel_scheduled_task", description=strings.CANCEL_DESCRIPTION),
        ]

    async def tools(self, context: Context) -> list[Tool]:
        return list(self._tools)

    async def _schedule_task(
        self,
        ctx: Context,
        prompt: Annotated[str, Field(description=strings.PROMPT)],
        at: Annotated[str | None, Field(description=strings.AT)] = None,
        every_minutes: Annotated[int | None, Field(description=strings.EVERY_MINUTES)] = None,
        daily: Annotated[str | None, Field(description=strings.DAILY)] = None,
        weekdays: Annotated[list[int] | None, Field(description=strings.WEEKDAYS)] = None,
    ) -> str:
        schedules = ctx.service(ScheduleService)
        if len(await schedules.list(ctx.session_id)) >= self.max_jobs_per_session:
            raise ToolError(f"当前会话的定时任务已达上限（{self.max_jobs_per_session} 个）", code="too_many")

        async def create() -> str:
            record = await schedules.create(
                ctx.session_id,
                prompt,
                at=at,
                every_minutes=every_minutes,
                daily=daily,
                weekdays=weekdays,
                timezone=self.timezone,
            )
            return record.id

        try:
            job_id = await ctx.step("create", create)
        except ValueError as error:
            raise ToolError(str(error), code="invalid_schedule") from None

        record = await schedules.get(job_id)
        return strings.CREATED.format(
            id=record.id, rule=describe(record), next_run=format_time(record.next_run, self.timezone)
        )

    async def _list_scheduled_tasks(self, ctx: Context) -> dict[str, Any]:
        tasks = [
            {
                "id": record.id,
                "prompt": record.prompt,
                "rule": describe(record),
                "paused": record.paused,
                "next_run": format_time(record.next_run, self.timezone),
            }
            for record in await ctx.service(ScheduleService).list(ctx.session_id)
        ]
        return {"now": format_time(time.time(), self.timezone), "tasks": tasks}

    async def _cancel_scheduled_task(
        self, ctx: Context, task_id: Annotated[str, Field(description=strings.TASK_ID)]
    ) -> str:
        schedules = ctx.service(ScheduleService)
        if task_id not in {record.id for record in await schedules.list(ctx.session_id)}:
            raise ToolError(f"当前会话中不存在定时任务 {task_id}", code="not_found")

        await schedules.delete(task_id)
        return strings.CANCELLED.format(id=task_id)


def describe(record: ScheduleRecord) -> str:
    if record.kind == "once":
        return strings.RULE_ONCE.format(at=format_time(record.at, record.timezone))
    if record.kind == "every":
        return strings.RULE_EVERY.format(minutes=record.every_minutes)
    if record.weekdays:
        days = "、".join(strings.WEEKDAY_NAMES[day - 1] for day in record.weekdays)
        return strings.RULE_WEEKLY.format(days=days, time=record.daily)
    return strings.RULE_DAILY.format(time=record.daily)


def format_time(timestamp: float | None, timezone: str) -> str:
    if timestamp is None:
        return strings.UNSCHEDULED
    return datetime.datetime.fromtimestamp(timestamp, ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M")
