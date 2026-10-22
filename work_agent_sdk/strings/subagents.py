from __future__ import annotations

# agent：说明按配置组合，未配置的模式不出现
AGENT_INTRO = "将任务委派给子智能体执行。子智能体看不到当前对话，只能看到你在 prompt 中写的任务说明。"
AGENT_FOREGROUND_MODE = "前台子智能体：等待其完成后返回其结果；一次回答中可委派多个，并行执行。"
AGENT_BACKGROUND_MODE = "后台子智能体：调用立即返回；子智能体持续存在，每轮结束时，其结果作为一条消息发给你。"
AGENT_SHARED_WORKSPACE = "子智能体与你使用同一工作区。"
AGENT_FOREGROUND = "- {name}（前台）：{description}"
AGENT_BACKGROUND = "- {name}（后台）：{description}"
AGENT_DYNAMIC = "- {name}（按需创建）：根据任务说明创建一个子智能体。{description}可用工具：{tools}"
AGENT_NO_TOOLS = "（无）"
AGENT_TYPE = "要委派的子智能体：\n{agents}"
AGENT_PROMPT = "完整的任务说明。子智能体看不到当前对话，请写明任务目标、背景以及需要返回的内容"
AGENT_DYNAMIC_BACKGROUND = "仅适用于 {name}：false（默认）为前台执行，等待其完成；true 为后台执行"
AGENT_DYNAMIC_TOOLS = "仅适用于 {name}：提供给子智能体的工具；省略时提供全部工具"

MESSAGE_AGENT_DESCRIPTION = "向后台子智能体发送消息，例如补充说明或新的要求。子智能体将继续执行，并在完成后提交结论。"
CLOSE_AGENT_DESCRIPTION = "关闭后台子智能体：停止其当前工作，并终止其启动的进程。"
LIST_AGENTS_DESCRIPTION = "列出可委派的子智能体，以及当前后台子智能体的状态（执行中、空闲、等待中）。"
AGENT_ID = "子智能体编号，形如 ses_xxx"
AGENT_MESSAGE = "要发送的消息内容"
MESSAGE_SENT = "已发送给 {name}（{id}），其完成后会提交结论"
AGENT_ALREADY_CLOSED = "{name}（{id}）已关闭"
AGENT_CLOSED = "已关闭 {name}（{id}）"
