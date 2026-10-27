# Schedules

```python
from work_agent_sdk import Scheduler, ScheduleService
```

## Scheduler

```python
Scheduler(*, timezone: str = "UTC", max_jobs_per_session: int = 20)
```

Toolset that lets the agent create scheduled tasks for the current session; add it to the `tools` parameter of `Agent`.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `timezone` | `str` | `"UTC"` | Time zone, e.g. `Asia/Shanghai` |
| `max_jobs_per_session` | `int` | `20` | Maximum number of tasks per session |

| Tool | Description |
| :-- | :-- |
| `schedule_task` | Create a scheduled task |
| `list_scheduled_tasks` | List the current session's scheduled tasks |
| `cancel_scheduled_task` | Delete a scheduled task |

## ScheduleService

Service returned by `runner.service(ScheduleService)`, for managing scheduled tasks from code.

| Method | Description |
| :-- | :-- |
| [`create(session_id, prompt, ...)`](#create) | Create a scheduled task; returns a [`ScheduleRecord`](#schedulerecord) |
| `list(session_id=None)` | Return scheduled tasks ordered by creation time. Returns tasks for all sessions when `session_id` is not set |
| `get(job_id)` | Return a scheduled task. Raises `LookupError` if it doesn't exist |
| `pause(job_id)` | Pause |
| `resume(job_id)` | Resume. Recurring tasks recompute their next run time from now |
| `run_now(job_id)` | Run once immediately; the existing schedule is unchanged |
| `delete(job_id)` | Delete |

### create()

```python
async def create(
    session_id: str,
    prompt: str,
    *,
    at: datetime | str | float | None = None,
    every_minutes: int | None = None,
    daily: str | None = None,
    weekdays: list[int] | None = None,
    timezone: str = "UTC",
) -> ScheduleRecord
```

Exactly one of `at`, `every_minutes` and `daily` must be set.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `session_id` | `str` | Required | Session ID. When the session closes, its tasks are deleted too |
| `prompt` | `str` | Required | Content sent to the session when the task is due |
| `at` | `datetime \| str \| float \| None` | `None` | Time to run once. Strings are ISO 8601; numbers are Unix timestamps. The task is deleted after it runs |
| `every_minutes` | `int \| None` | `None` | Interval between runs (minutes); minimum 1 |
| `daily` | `str \| None` | `None` | Time of day to run, e.g. `"09:00"` |
| `weekdays` | `list[int] \| None` | `None` | Days of the week to run; `1` is Monday and `7` is Sunday. Used together with `daily` |
| `timezone` | `str` | `"UTC"` | Time zone used by `at` and `daily` |

## ScheduleRecord

| Field | Type | Description |
| :-- | :-- | :-- |
| `id` | `str` | Task ID |
| `session_id` | `str` | Session ID |
| `prompt` | `str` | Content sent to the session when the task is due |
| `kind` | `str` | Kind. Values: `once` (run once), `every` (run at an interval) or `daily` (run daily or weekly) |
| `at`, `every_minutes`, `daily`, `weekdays`, `timezone` | | Parameters given at creation. `at` is a Unix timestamp |
| `next_run` | `float \| None` | Next run time (Unix timestamp) |
| `last_run` | `float \| None` | Last run time (Unix timestamp) |
| `paused` | `bool` | Whether paused |
| `created_at` | `float` | Creation time (Unix timestamp) |

## Examples

- [schedules/schedules.py](../../examples/schedules/schedules.py): agent and code create scheduled tasks, run one immediately, get the results
