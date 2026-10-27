from __future__ import annotations

SCHEDULE_DESCRIPTION = (
    "Create a scheduled task; when the scheduled time arrives you'll receive the task description and carry it out. Provide exactly one of at (run once), every_minutes (every N minutes) "
    "and daily (at a fixed time each day, optionally limited to certain days with weekdays). All times are interpreted in {timezone}; "
    "if you need the current time, call list_scheduled_tasks."
)
LIST_DESCRIPTION = "List the current session's scheduled tasks and return the current time."
CANCEL_DESCRIPTION = "Cancel a scheduled task."
PROMPT = "The work to do when the scheduled time arrives, written as a complete task description"
AT = "Time to run once, formatted YYYY-MM-DDTHH:MM, e.g. 2026-10-16T15:00"
EVERY_MINUTES = "Interval between runs (minutes)"
DAILY = "Time of day to run, formatted HH:MM, e.g. 09:00"
WEEKDAYS = "Used with daily to limit which days of the week it runs; 1 is Monday and 7 is Sunday, e.g. [1, 2, 3, 4, 5]"
TASK_ID = "Scheduled task ID"
CREATED = "Created scheduled task {id} ({rule}); next run: {next_run}"
CANCELLED = "Cancelled scheduled task {id}"
UNSCHEDULED = "not scheduled"
FIRED = "Scheduled task {id} is due. Please do the following:\n{prompt}"

RULE_ONCE = "once at {at}"
RULE_EVERY = "every {minutes} minutes"
RULE_DAILY = "every day at {time}"
RULE_WEEKLY = "every {days} at {time}"
WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
