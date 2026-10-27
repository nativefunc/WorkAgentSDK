from __future__ import annotations

# agent: the description is assembled from the configuration; unconfigured modes don't appear
AGENT_INTRO = "Delegate a task to a subagent. The subagent can't see the current conversation, only the task description you write in prompt."
AGENT_FOREGROUND_MODE = "Foreground subagents: wait for them to finish and return their results; you can delegate several in one response and they run in parallel."
AGENT_BACKGROUND_MODE = "Background subagents: the call returns immediately; the subagent keeps existing, and at the end of each of its turns its result is sent to you as a message."
AGENT_SHARED_WORKSPACE = "Subagents use the same workspace as you."
AGENT_FOREGROUND = "- {name} (foreground): {description}"
AGENT_BACKGROUND = "- {name} (background): {description}"
AGENT_DYNAMIC = "- {name} (created on demand): creates a subagent from the task description. {description}Available tools: {tools}"
AGENT_NO_TOOLS = "(none)"
AGENT_TYPE = "The subagent to delegate to:\n{agents}"
AGENT_PROMPT = "The complete task description. The subagent can't see the current conversation, so state the goal, the background and what should be returned"
AGENT_DYNAMIC_BACKGROUND = "Only for {name}: false (default) runs in the foreground and waits for it to finish; true runs in the background"
AGENT_DYNAMIC_TOOLS = "Only for {name}: tools given to the subagent; all tools when omitted"

MESSAGE_AGENT_DESCRIPTION = "Send a message to a background subagent, such as clarifications or new requirements. The subagent continues working and submits its conclusion when done."
CLOSE_AGENT_DESCRIPTION = "Close a background subagent: stop its current work and terminate the processes it started."
LIST_AGENTS_DESCRIPTION = "List the subagents that can be delegated to, and the status of current background subagents (running, idle, waiting)."
AGENT_ID = "Subagent ID, like ses_xxx"
AGENT_MESSAGE = "The message to send"
MESSAGE_SENT = "Sent to {name} ({id}); it will submit its conclusion when done"
AGENT_ALREADY_CLOSED = "{name} ({id}) is already closed"
AGENT_CLOSED = "Closed {name} ({id})"
