from __future__ import annotations

LOAD_SKILL_DESCRIPTION = "Read a skill's full instructions and file location, then follow the instructions. When the user gives the directory a skill is in, load it with path."
LOAD_SKILL_NAMED = "Skills that can be loaded by name:"
LOAD_SKILL_ITEM = "- {name}: {description}"
LOAD_SKILL_WORKSPACE = "Skills that come with the workspace can also be loaded by name; see the notice in the conversation for the list."
LOAD_SKILL_NAME = "Skill name"
LOAD_SKILL_PATH = "Path to the skill directory, used when the user specifies a directory"
LOAD_SKILL_FILE = "Read only one file in the skill (e.g. references/guide.md), with the path relative to the skill directory"

SKILL_WITH_FILES = "The files of skill {name} are at {location}{note}; scripts in it can be run with shell."
SKILL_WITHOUT_FILES = "Skill {name}. {note}"
SKILL_COMPATIBILITY = "\nEnvironment requirements (provided by the skill author): {compatibility}"
SKILL_ALLOWED_TOOLS = "\nTools this skill uses: {tools}"
NOTE_READ_ONLY = " (read-only)"
NOTE_WORKSPACE_SKILL = " (a skill that comes with the workspace's node)"
NOTE_NO_WORKSPACE = "No workspace is configured for this session, so scripts in the skill can't run; reference files can be read with load_skill(name=..., file=...)."
NOTE_WORKSPACE_UNAVAILABLE = "The workspace is currently unavailable ({error}), so scripts in the skill can't run for now; reference files can be read with file=."

SELECTED = "The user asked to use skill {name} for this turn.\n{text}"
WORKSPACE_SKILLS = "The workspace comes with the following skills, which can be loaded with load_skill(name=...):"
WORKSPACE_SKILL_ITEM = "- {name} ({path}): {description}"
WORKSPACE_SKILLS_NONE = "The workspace no longer has any skills of its own."
