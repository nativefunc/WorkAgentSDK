# Skills

```python
from work_agent_sdk import Skills
```

## Skills

```python
Skills(*sources: str, workspace_roots: Sequence[str] = (".agents/skills", ".claude/skills"))
```

Toolset that provides skills; add it to the `tools` parameter of `Agent`. Set `skills` in `send()`'s `metadata`, e.g. `metadata={"skills": ["release-notes"]}`, to load those skills before the turn starts. When the session has a workspace, the model can run the skill's scripts with `Shell`, and the skill's files are read-only; when the session has no workspace, the model can only read `SKILL.md`.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `sources` | `str` | `()` | Directories on the local machine containing skills; several may be passed. Each subdirectory containing a `SKILL.md` is one skill |
| `workspace_roots` | `Sequence[str]` | `(".agents/skills", ".claude/skills")` | Directories in the workspace containing skills, relative to the workspace. Set to `()` to not use skills from the workspace |

| Tool | Description |
| :-- | :-- |
| `load_skill` | Load a skill, or read another file in a skill |

## SKILL.md fields

`SKILL.md` starts with a YAML header:

```markdown
---
name: release-notes
description: Write release notes from the commit history and suggest the next version number. Use when the user asks for release notes or to decide a version number.
---

# Writing release notes

...
```

| Field | Description |
| :-- | :-- |
| `name` | Required. Skill name; lowercase letters, digits and `-` only, up to 64 characters. Should match the directory name |
| `description` | Required. What the skill is for and when to use it, up to 1024 characters. The model decides when to load it based on this |
| `allowed-tools` | Tools the skill needs. Sent to the model when the skill is loaded |
| `compatibility` | Environments the skill works in. Sent to the model when the skill is loaded |

Skills whose fields don't meet these requirements are not offered to the model. `SKILL.md` can be at most 1 MB, other files at most 256 KB.

## Examples

- [skills](../../examples/skills): write and use skills, run scripts in a skill, pick the skills used for a turn
