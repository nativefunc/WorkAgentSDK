from __future__ import annotations

SCHEDULE_DESCRIPTION = (
    "创建定时任务，到达设定时间时将收到任务说明并执行。at（执行一次）、every_minutes（每隔若干分钟）"
    "与 daily（每天定点，可用 weekdays 限定星期几）须且仅须提供其一。时间均按 {timezone} 解释；"
    "需要当前时间时，可调用 list_scheduled_tasks 获取。"
)
LIST_DESCRIPTION = "列出当前会话的定时任务，并返回当前时间。"
CANCEL_DESCRIPTION = "取消一个定时任务。"
PROMPT = "到达设定时间时要执行的工作，写成完整的任务说明"
AT = "执行一次的时间，格式为 YYYY-MM-DDTHH:MM，例如 2026-10-16T15:00"
EVERY_MINUTES = "执行间隔（分钟）"
DAILY = "每天执行的时刻，格式为 HH:MM，例如 09:00"
WEEKDAYS = "与 daily 一起使用，限定星期几执行，1 为星期一、7 为星期日，例如 [1, 2, 3, 4, 5]"
TASK_ID = "定时任务编号"
CREATED = "已创建定时任务 {id}（{rule}），下次执行时间：{next_run}"
CANCELLED = "已取消定时任务 {id}"
UNSCHEDULED = "未排期"
FIRED = "定时任务 {id} 已到执行时间，请执行：\n{prompt}"

RULE_ONCE = "{at} 执行一次"
RULE_EVERY = "每 {minutes} 分钟"
RULE_DAILY = "每天 {time}"
RULE_WEEKLY = "每周{days} {time}"
WEEKDAY_NAMES = ("一", "二", "三", "四", "五", "六", "日")
