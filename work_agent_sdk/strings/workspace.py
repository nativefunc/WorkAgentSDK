from __future__ import annotations

SHELL_DESCRIPTION = (
    "Run a shell command in the workspace and return its output. The working directory is the workspace root; write temporary files to $TMPDIR.\n"
    "Commands run in the workspace sandbox; see the environment description in the conversation for the specific restrictions."
)
SHELL_UNSANDBOXED = (
    "If a command is blocked by the sandbox and really needs to run, set unsandboxed=true, put the question for the user in unsandboxed_reason, "
    "and run it again; once the user approves, the command runs outside the sandbox. There's no need to ask the user in your reply beforehand."
)
SHELL_TIMEOUT = (
    "A foreground command that is still running after {timeout:g} seconds (at most {max_timeout:g} seconds) becomes a background process. "
    "When a background process ends, a notice with the exit code and the last output appears in the conversation; "
    "to check the output earlier, send input or terminate the process, use shell_input."
)
SHELL_BACKGROUND = (
    "Start long-running commands (e.g. training, servers, bulk scraping) with background=true. "
    "Don't put commands in the background yourself with nohup, & or setsid; otherwise the framework can't track the process or show its output."
)
SHELL_COMMAND = "The command to run"
SHELL_TIMEOUT_ARG = "Maximum seconds to wait; after the timeout the command keeps running in the background"
SHELL_BACKGROUND_ARG = "Whether to start it directly in the background, for training, long-running servers, etc."
SHELL_UNSANDBOXED_ARG = "Whether to run this command outside the sandbox, which needs user approval; only use it when the command was blocked by the sandbox and really needs to run"
SHELL_UNSANDBOXED_REASON_ARG = "Required when unsandboxed=true: the question for the user, e.g. \"Allow installing the project dependencies?\""

SHELL_STARTED_IN_BACKGROUND = (
    "Started background process {process_id}. A notice will appear in the conversation when it ends; to check its output, use shell_input."
)
SHELL_MOVED_TO_BACKGROUND = (
    "[The command was still running after {wait:g} seconds and became background process {process_id}. "
    "A notice will appear in the conversation when it ends; to check its output or terminate it, use shell_input]"
)
SHELL_NO_OUTPUT = "(no output)"
SHELL_OUTPUT_TRUNCATED = "[Output too long; the middle part was omitted. For the full content, redirect the output to a file and inspect it with grep, head or tail]"
SHELL_EXIT_CODE = "[exit code {exit_code}]"

SHELL_INPUT_DESCRIPTION = "Read new output from a background process, write to its standard input, or terminate it."
SHELL_INPUT_PROCESS_ID = "Process ID, like p_xxx"
SHELL_INPUT_TEXT = "Content to write to standard input; a newline is appended automatically. Leave empty to write nothing"
SHELL_INPUT_WAIT = "Maximum seconds to wait for new output or for the process to end"
SHELL_INPUT_KILL = "Whether to terminate the process"
SHELL_INPUT_NO_OUTPUT = "(no new output)"
SHELL_INPUT_ENDED = "[Process ended, exit code {exit_code}]"
SHELL_INPUT_RUNNING = "[Process {process_id} is still running]"

# The workspace section of the environment description: lists the settings actually in effect, item by item
FACTS_TITLE = "Workspace"
FACTS_ITEM = "- {name}: {value}"
FACTS_SEPARATOR = ", "
FACTS_NODE = "Node"
FACTS_STATUS = "Node status"
FACTS_ONLINE = "online"
FACTS_OFFLINE = "offline"
FACTS_OS = "OS"
FACTS_SHELL = "Shell"
FACTS_PATH = "Path"
FACTS_COMMANDS = "Running commands"
FACTS_ALLOWED = "allowed"
FACTS_NOT_ALLOWED = "not allowed"
FACTS_SANDBOX = "Sandbox"
FACTS_SANDBOX_NONE = "none"
FACTS_WRITABLE = "Writable directories"
FACTS_DOMAINS = "Allowed domains"
FACTS_DOMAINS_NONE = "none"
FACTS_UNSANDBOXED = "Running outside the sandbox"
FACTS_UNSANDBOXED_ALLOWED = "requires user approval"
FACTS_SHARED_FOLDER = "Shared folder"
FACTS_SHARED_FOLDER_VALUE = "{name} → {path}"
FACTS_DESCRIPTION = "Description"

VIEW_IMAGE_DESCRIPTION_WORKSPACE = (
    "View an image (png, jpg, gif or webp). The path can be relative to the workspace or a full path."
)
VIEW_IMAGE_DESCRIPTION_LOCAL = "View an image (png, jpg, gif or webp). The path must be a full path."
VIEW_IMAGE_PATH = "Image path"
VIEW_IMAGE_NOT_ABSOLUTE = "{path} is not a full path; give the full path"
VIEW_IMAGE_FILE_TOO_LARGE = "File exceeds {limit} MB"
VIEW_IMAGE_CAPTION = "Image {path}:"

PROCESS_NO_OUTPUT = "(no output)"
PROCESS_ENDED_WITH_DETAIL = "Background process {id} ({command}) ended: {detail}\nLast output:\n{tail}"
PROCESS_KILLED = "Background process {id} ({command}) was terminated. Last output:\n{tail}"
PROCESS_EXITED = "Background process {id} ({command}) ended with exit code {exit_code}. Last output:\n{tail}"
PROCESS_CONNECTION_LOST = "The connection to the node dropped and the process was terminated: {error}"
PROCESS_FAILED = "Process error: {error}"
PROCESS_BACKEND_RESTARTED = "The backend restarted and the process was terminated"
PROCESS_OUTPUT_GAP = "\n[{size} bytes of output in between were not saved]\n"
