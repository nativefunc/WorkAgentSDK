from __future__ import annotations

import asyncio
import datetime
import logging
import re
import time
from zoneinfo import ZoneInfo

import work_agent_sdk.strings.schedules as strings
from work_agent_sdk.core.errors import SessionClosed
from work_agent_sdk.core.messages import CustomMessage
from work_agent_sdk.core.service import RunnerAPI, Service, SessionRef
from work_agent_sdk.schedules.store import (
    ScheduleRecord,
    ScheduleStore,
    SqliteScheduleStore,
)

logger = logging.getLogger("work_agent_sdk")

CHECK_INTERVAL = 20
DAILY_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def next_daily(daily: str, weekdays: list[int] | None, timezone: str, after: float) -> float:
    hour, minute = (int(part) for part in daily.split(":"))
    zone = ZoneInfo(timezone)
    today = datetime.datetime.fromtimestamp(after, zone).date()
    for offset in range(8):
        day = today + datetime.timedelta(days=offset)
        if weekdays and day.isoweekday() not in weekdays:
            continue

        moment = datetime.datetime.combine(day, datetime.time(hour, minute), zone).timestamp()
        if moment > after:
            return moment

    raise ValueError(f"Invalid weekdays value {weekdays}")


def next_run(record: ScheduleRecord, after: float) -> float | None:
    if record.kind == "once":
        return record.at if record.last_run is None else None
    if record.kind == "every":
        assert record.every_minutes is not None
        return after + record.every_minutes * 60

    assert record.daily is not None
    return next_daily(record.daily, record.weekdays, record.timezone, after)


def to_timestamp(at: datetime.datetime | str | float, timezone: str) -> float:
    if isinstance(at, (int, float)):
        return float(at)
    if isinstance(at, str):
        at = datetime.datetime.fromisoformat(at)
    if at.tzinfo is None:
        at = at.replace(tzinfo=ZoneInfo(timezone))

    return at.timestamp()


class ScheduleService(Service):
    """store is the storage for scheduled tasks; uses data_dir/ext/schedules/schedules.db by default."""

    def __init__(self, *, store: ScheduleStore | None = None) -> None:
        self.store = store
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def attach(self, api: RunnerAPI) -> None:
        await super().attach(api)
        if self.store is None:
            self.store = SqliteScheduleStore(api.files("schedules") / "schedules.db")

    @property
    def jobs(self) -> ScheduleStore:
        assert self.store is not None, "ScheduleService hasn't been registered with a Runner"
        return self.store

    async def create(
        self,
        session_id: str,
        prompt: str,
        *,
        at: datetime.datetime | str | float | None = None,
        every_minutes: int | None = None,
        daily: str | None = None,
        weekdays: list[int] | None = None,
        timezone: str = "UTC",
    ) -> ScheduleRecord:
        if sum(value is not None for value in (at, every_minutes, daily)) != 1:
            raise ValueError("Invalid arguments")

        ZoneInfo(timezone)

        if weekdays is not None and daily is None:
            raise ValueError("weekdays can only be used together with daily")
        if weekdays is not None and (not weekdays or any(day not in range(1, 8) for day in weekdays)):
            raise ValueError("Each item in weekdays must be 1 (Monday) to 7 (Sunday)")

        now = time.time()
        if at is not None:
            moment = to_timestamp(at, timezone)
            if moment <= now:
                raise ValueError("at must be in the future")
            record = ScheduleRecord(
                session_id=session_id,
                prompt=prompt,
                kind="once",
                at=moment,
                timezone=timezone,
            )
        elif every_minutes is not None:
            if every_minutes < 1:
                raise ValueError(f"Invalid every_minutes value {every_minutes}; must be at least 1")
            record = ScheduleRecord(
                session_id=session_id, prompt=prompt, kind="every", every_minutes=every_minutes, timezone=timezone
            )
        else:
            assert daily is not None

            if not DAILY_TIME.match(daily):
                raise ValueError(f"Invalid daily value {daily!r}; format is HH:MM, e.g. 09:00")

            record = ScheduleRecord(
                session_id=session_id,
                prompt=prompt,
                kind="daily",
                daily=daily,
                weekdays=sorted(set(weekdays)) if weekdays else None,
                timezone=timezone,
            )

        record.next_run = next_run(record, now)
        async with self._lock:
            await self.jobs.put(record)

        return record

    async def list(self, session_id: str | None = None) -> list[ScheduleRecord]:
        return await self.jobs.list(session_id)

    async def get(self, job_id: str) -> ScheduleRecord:
        record = await self.jobs.get(job_id)
        if record is None:
            raise LookupError(f"Scheduled task not found: {job_id}")
        return record

    async def pause(self, job_id: str) -> None:
        async with self._lock:
            record = await self.get(job_id)
            record.paused = True
            await self.jobs.put(record)

    async def resume(self, job_id: str) -> None:
        async with self._lock:
            record = await self.get(job_id)
            record.paused = False
            record.next_run = next_run(record, time.time())
            await self.jobs.put(record)

    async def run_now(self, job_id: str) -> None:
        record = await self.get(job_id)
        if not await self._deliver(record, scheduled_at=time.time()):
            await self.delete(record.id)

    async def delete(self, job_id: str) -> None:
        async with self._lock:
            await self.jobs.delete(job_id)

    async def runner_started(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="work_agent_sdk:schedules")

    async def runner_stopping(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def runner_stopped(self) -> None:
        if self.store is not None:
            await self.store.close()

    async def session_closing(self, session: SessionRef) -> None:
        for record in await self.list(session.id):
            await self.delete(record.id)

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_due_jobs()
            except Exception:
                logger.exception("Error checking scheduled tasks")
            await asyncio.sleep(CHECK_INTERVAL)

    async def run_due_jobs(self) -> None:
        moment = time.time()
        async with self._lock:
            for record in await self.jobs.list():
                if record.paused or record.next_run is None or record.next_run > moment:
                    continue

                try:
                    delivered = await self._deliver(record, scheduled_at=record.next_run)
                except Exception:
                    logger.exception("Error triggering scheduled task %s; will retry on the next check", record.id)
                    continue

                record.last_run = moment
                record.next_run = next_run(record, moment) if delivered else None
                if record.next_run is None:
                    await self.jobs.delete(record.id)
                else:
                    await self.jobs.put(record)

    async def _deliver(self, record: ScheduleRecord, *, scheduled_at: float) -> bool:
        if await self.api.session(record.session_id) is None:
            return False

        message = CustomMessage(
            "schedule.fired",
            data={"schedule_id": record.id, "prompt": record.prompt, "scheduled_at": scheduled_at},
            for_model=strings.FIRED.format(id=record.id, prompt=record.prompt),
        )
        metadata = {"schedule_id": record.id, "scheduled_at": scheduled_at}
        try:
            await self.api.enqueue(record.session_id, message, source="schedule", metadata=metadata)
        except (SessionClosed, KeyError):
            return False

        return True
