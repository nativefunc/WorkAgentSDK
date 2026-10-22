from __future__ import annotations

LOAD_SKILL_DESCRIPTION = "读取技能的完整说明及其文件位置，然后按说明执行。用户给出技能所在目录时，使用 path 加载。"
LOAD_SKILL_NAMED = "可按名称加载的技能："
LOAD_SKILL_ITEM = "- {name}：{description}"
LOAD_SKILL_WORKSPACE = "工作区自带的技能也可按名称加载，具体列表见对话中的通知。"
LOAD_SKILL_NAME = "技能名称"
LOAD_SKILL_PATH = "技能目录的路径，在用户指定目录时使用"
LOAD_SKILL_FILE = "仅读取技能中的某个文件（如 references/guide.md），路径相对于技能目录"

SKILL_WITH_FILES = "技能 {name} 的文件位于 {location}{note}，其中的脚本可通过 shell 运行。"
SKILL_WITHOUT_FILES = "技能 {name}。{note}"
SKILL_COMPATIBILITY = "\n运行环境要求（由技能作者提供）：{compatibility}"
SKILL_ALLOWED_TOOLS = "\n该技能会使用的工具：{tools}"
NOTE_READ_ONLY = "（只读）"
NOTE_WORKSPACE_SKILL = "（工作区所在节点自带的技能）"
NOTE_NO_WORKSPACE = "当前会话未配置工作区，技能中的脚本无法运行；参考文件可通过 load_skill(name=..., file=...) 读取。"
NOTE_WORKSPACE_UNAVAILABLE = "工作区当前不可用（{error}），技能中的脚本暂时无法运行；参考文件可通过 file= 读取。"

SELECTED = "用户要求本轮使用技能 {name}。\n{text}"
WORKSPACE_SKILLS = "工作区自带以下技能，可通过 load_skill(name=...) 加载："
WORKSPACE_SKILL_ITEM = "- {name}（{path}）：{description}"
WORKSPACE_SKILLS_NONE = "工作区中已无自带的技能。"
