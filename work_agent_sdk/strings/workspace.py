from __future__ import annotations

SHELL_DESCRIPTION = (
    "在工作区中执行一条 shell 命令并返回输出。工作目录为工作区根目录，临时文件请写入 $TMPDIR。\n"
    "命令在工作区的沙箱中执行，具体限制见对话中的运行环境说明。"
)
SHELL_UNSANDBOXED = (
    "若命令被沙箱拦截且确有必要执行，请设置 unsandboxed=true，并在 unsandboxed_reason 中写明向用户提出的问题，"
    "然后重新执行；用户批准后，命令将在沙箱外执行。无需事先在回复中询问用户。"
)
SHELL_TIMEOUT = (
    "前台命令运行超过 {timeout:g} 秒（上限 {max_timeout:g} 秒）仍未结束时，将转为后台进程。"
    "后台进程结束时，对话中会出现一条通知，包含退出码和末尾输出；"
    "如需提前查看输出、写入输入或终止进程，请使用 shell_input。"
)
SHELL_BACKGROUND = (
    "长时间运行的命令（如训练、服务、批量抓取）请使用 background=true 启动。"
    "不要在命令中使用 nohup、& 或 setsid 自行转入后台，否则框架无法跟踪该进程，也无法查看其输出。"
)
SHELL_COMMAND = "要执行的命令"
SHELL_TIMEOUT_ARG = "最长等待秒数；超时后命令转入后台继续运行"
SHELL_BACKGROUND_ARG = "是否直接在后台启动，适用于训练、长期运行的服务等"
SHELL_UNSANDBOXED_ARG = "是否在沙箱外执行该命令，需用户批准；仅在命令被沙箱拦截且确有必要时使用"
SHELL_UNSANDBOXED_REASON_ARG = "unsandboxed=true 时必填：向用户提出的问题，例如“是否允许安装项目依赖？”"

SHELL_STARTED_IN_BACKGROUND = (
    "已在后台启动进程 {process_id}。进程结束时对话中会出现通知；如需查看输出，请使用 shell_input。"
)
SHELL_MOVED_TO_BACKGROUND = (
    "[命令运行超过 {wait:g} 秒仍未结束，已转为后台进程 {process_id}。"
    "进程结束时对话中会出现通知；如需查看输出或终止进程，请使用 shell_input]"
)
SHELL_NO_OUTPUT = "（无输出）"
SHELL_OUTPUT_TRUNCATED = "[输出过长，中间部分已省略。如需完整内容，请将输出重定向到文件，再用 grep、head 或 tail 查看]"
SHELL_EXIT_CODE = "[退出码 {exit_code}]"

SHELL_INPUT_DESCRIPTION = "读取后台进程的新输出，向其标准输入写入内容，或终止该进程。"
SHELL_INPUT_PROCESS_ID = "进程编号，形如 p_xxx"
SHELL_INPUT_TEXT = "写入标准输入的内容，末尾自动追加换行；不写入时留空"
SHELL_INPUT_WAIT = "等待新输出或进程结束的最长秒数"
SHELL_INPUT_KILL = "是否终止该进程"
SHELL_INPUT_NO_OUTPUT = "（无新输出）"
SHELL_INPUT_ENDED = "[进程已结束，退出码 {exit_code}]"
SHELL_INPUT_RUNNING = "[进程 {process_id} 仍在运行]"

# 运行环境说明中的工作区部分：逐项列出当前实际生效的设置
FACTS_TITLE = "工作区"
FACTS_ITEM = "- {name}：{value}"
FACTS_SEPARATOR = "、"
FACTS_NODE = "节点"
FACTS_STATUS = "节点状态"
FACTS_ONLINE = "在线"
FACTS_OFFLINE = "离线"
FACTS_OS = "系统"
FACTS_SHELL = "Shell"
FACTS_PATH = "路径"
FACTS_COMMANDS = "命令执行"
FACTS_ALLOWED = "允许"
FACTS_NOT_ALLOWED = "不允许"
FACTS_SANDBOX = "沙箱"
FACTS_SANDBOX_NONE = "无"
FACTS_WRITABLE = "可写目录"
FACTS_DOMAINS = "允许访问的域名"
FACTS_DOMAINS_NONE = "无"
FACTS_DOMAINS_ANY = "不限"
FACTS_UNSANDBOXED = "沙箱外执行"
FACTS_UNSANDBOXED_ALLOWED = "需用户批准"
FACTS_SHARED_FOLDER = "共享文件夹"
FACTS_SHARED_FOLDER_VALUE = "{name} → {path}"
FACTS_DESCRIPTION = "说明"

VIEW_IMAGE_DESCRIPTION_WORKSPACE = "查看一张图片（png、jpg、gif 或 webp）。路径可以是工作区内的相对路径，也可以是完整路径。"
VIEW_IMAGE_DESCRIPTION_LOCAL = "查看一张图片（png、jpg、gif 或 webp）。路径须为完整路径。"
VIEW_IMAGE_PATH = "图片路径"
VIEW_IMAGE_NOT_ABSOLUTE = "{path} 不是完整路径；请给出完整路径"
VIEW_IMAGE_FILE_TOO_LARGE = "文件超过 {limit} MB"
VIEW_IMAGE_CAPTION = "图片 {path}："

PROCESS_NO_OUTPUT = "（无输出）"
PROCESS_ENDED_WITH_DETAIL = "后台进程 {id}（{command}）已结束：{detail}\n末尾输出：\n{tail}"
PROCESS_KILLED = "后台进程 {id}（{command}）已被终止。末尾输出：\n{tail}"
PROCESS_EXITED = "后台进程 {id}（{command}）已结束，退出码 {exit_code}。末尾输出：\n{tail}"
PROCESS_CONNECTION_LOST = "与节点的连接已断开，进程已终止：{error}"
PROCESS_FAILED = "进程出错：{error}"
PROCESS_BACKEND_RESTARTED = "后端已重启，进程已终止"
PROCESS_OUTPUT_GAP = "\n[中间有 {size} 字节的输出未保存]\n"
