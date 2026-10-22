from __future__ import annotations

import asyncio
import logging
import weakref
from collections.abc import Sequence
from typing import Annotated, Any

from pydantic import Field

import work_agent_sdk.strings.skills as strings
from work_agent_sdk.core.errors import ToolError
from work_agent_sdk.core.hooks import Hooks
from work_agent_sdk.core.messages import CustomMessage
from work_agent_sdk.core.tool import Context, Tool, Toolset
from work_agent_sdk.skills.loader import (
    MAX_MANIFEST_BYTES,
    MAX_REFERENCE_BYTES,
    Skill,
    SkillDirectory,
    WorkspaceScan,
    parse_skill,
    read_reference,
    skill_text,
    workspace_skills,
)
from work_agent_sdk.skills.placement import Placement
from work_agent_sdk.workspace.service import BoundWorkspace

logger = logging.getLogger("work_agent_sdk")


class _SelectedSkills(Hooks):
    def __init__(self, owner: Skills) -> None:
        self.owner = owner

    async def before_turn(self, ctx: Any, message: Any) -> Any:
        turn = ctx.turn
        names = (turn.metadata or {}).get("skills") if turn is not None else None
        if not names:
            return None

        for name in names:
            text = await self.owner.selected_skill_text(ctx, str(name))
            if text is not None:
                await ctx.add_message(
                    CustomMessage(
                        "skill.loaded", data={"name": name}, for_model=strings.SELECTED.format(name=name, text=text)
                    )
                )

        return None

    def __repr__(self) -> str:
        return "Skills.selected"


class _WorkspaceSkillList(Hooks):
    def __init__(self, owner: Skills) -> None:
        self.owner = owner

    async def before_turn(self, ctx: Any, message: Any) -> Any:
        if not self.owner.workspace_roots:
            return None

        try:
            workspace = await ctx.resource("workspace", wait=False)
        except Exception as error:
            # 列出技能只是附带的通知，工作区出错时跳过，不影响本轮
            logger.warning("无法读取工作区以列出其中的技能：%s", error)
            return None

        if workspace is None:
            return None

        try:
            skills = await self.owner.current_workspace_skills(workspace)
        except Exception as error:
            logger.warning("无法列出工作区中的技能：%s", error)
            return None

        listed = [
            {"name": skill.name, "description": skill.description, "path": workspace.relative(skill.source_dir)}
            for skill in skills.values()
        ]
        if listed == await self._last_listed(ctx):
            return None

        if listed:
            lines = [strings.WORKSPACE_SKILLS]
            lines += [strings.WORKSPACE_SKILL_ITEM.format(**item) for item in listed]
            text = "\n".join(lines)
        else:
            text = strings.WORKSPACE_SKILLS_NONE

        await ctx.add_message(CustomMessage("skills.available", data=listed, display=False, for_model=text))
        return None

    @staticmethod
    async def _last_listed(ctx: Any) -> list[dict[str, str]]:
        for item in reversed(await ctx.session.history()):
            if getattr(item, "kind", None) == "skills.available":
                return list(item.data or [])
        return []

    def __repr__(self) -> str:
        return "Skills.workspace_list"


DEFAULT_WORKSPACE_ROOTS = (".agents/skills", ".claude/skills")


class Skills(Toolset):
    name = "skills"
    description = "按需加载技能"

    def __init__(self, *sources: str, workspace_roots: Sequence[str] = DEFAULT_WORKSPACE_ROOTS) -> None:
        """sources 为后端上的技能目录；workspace_roots 为工作区所在节点自带的技能目录，传入 () 表示不使用。"""
        self.directories = [SkillDirectory(path) for path in sources]
        self.workspace_roots = tuple(workspace_roots)

        # 工作区自带技能的上次扫描结果（按绑定的工作区），用于只读取有变化的 SKILL.md；绑定失效后随之释放
        self._scanned: weakref.WeakKeyDictionary[Any, WorkspaceScan] = weakref.WeakKeyDictionary()
        self.placement = Placement()
        super().__init__(hooks=[_SelectedSkills(self), _WorkspaceSkillList(self)])
        self._tool = Tool(
            self._load_skill,
            name="load_skill",
            description=self._describe,
            parallel=True,
            annotations={"read_only": True},
        )

    def __repr__(self) -> str:
        return f"Skills({[directory.path for directory in self.directories]})"

    async def tools(self, ctx: Context) -> list[Tool]:
        return [self._tool]

    def find(self, name: str) -> tuple[SkillDirectory, Skill] | None:
        for directory in self.directories:
            skill = directory.list().get(name)
            if skill is not None:
                return directory, skill
        return None

    async def _workspace(self, ctx: Any) -> BoundWorkspace | None:
        try:
            return await ctx.resource("workspace")
        except ToolError:
            raise
        except Exception as error:
            raise ToolError(f"工作区当前不可用：{error}", code="workspace_unavailable") from None

    async def current_workspace_skills(self, workspace: BoundWorkspace) -> dict[str, Skill]:
        if not self.workspace_roots:
            return {}

        skills, self._scanned[workspace] = await workspace_skills(
            workspace, self.workspace_roots, self._scanned.get(workspace)
        )
        return skills

    async def _workspace_skill(self, ctx: Any, name: str) -> Skill | None:
        if not self.workspace_roots:
            return None

        workspace = await self._workspace(ctx)
        if workspace is None:
            return None

        try:
            return (await self.current_workspace_skills(workspace)).get(name)
        except ToolError:
            raise
        except Exception as error:
            raise ToolError(f"工作区当前不可用：{error}", code="workspace_unavailable") from None

    async def _describe(self, ctx: Any) -> str:
        lines = [strings.LOAD_SKILL_DESCRIPTION]

        # 只列出后端上的技能：工作区自带的技能另有 skills.available 消息，避免为生成说明而连接节点
        listed = {name: skill for directory in self.directories for name, skill in directory.list().items()}
        if listed:
            lines.append(strings.LOAD_SKILL_NAMED)
            lines += [strings.LOAD_SKILL_ITEM.format(name=s.name, description=s.description) for s in listed.values()]

        if self.workspace_roots:
            lines.append(strings.LOAD_SKILL_WORKSPACE)

        return "\n".join(lines)

    async def _load_skill(
        self,
        ctx: Context,
        name: Annotated[str | None, Field(description=strings.LOAD_SKILL_NAME)] = None,
        path: Annotated[str | None, Field(description=strings.LOAD_SKILL_PATH)] = None,
        file: Annotated[str | None, Field(description=strings.LOAD_SKILL_FILE)] = None,
    ) -> str:
        if bool(name) == bool(path):
            raise ToolError("name 与 path 须且仅须提供其一", code="invalid_arguments")
        if path:
            return await self._load_from_path(ctx, path, file)

        assert name is not None
        found = self.find(name)
        if found is not None:
            directory, skill = found
            if file:
                return await asyncio.to_thread(read_reference, skill.source_dir, file)
            return await self._place_and_describe(ctx, skill)

        workspace_skill = await self._workspace_skill(ctx, name)
        if workspace_skill is not None:
            if file:
                return await self._read_skill_file(ctx, workspace_skill.source_dir, file)
            return skill_text(workspace_skill, workspace_skill.source_dir, note=strings.NOTE_WORKSPACE_SKILL)
        raise ToolError(f"技能 {name} 不存在；如果用户给出的是目录，请使用 path 加载", code="not_found")

    async def _load_from_path(self, ctx: Any, path: str, file: str | None) -> str:
        workspace = await self._workspace(ctx)
        if workspace is None:
            raise ToolError("当前会话未配置工作区，无法按目录加载技能", code="no_workspace")

        style = workspace.style
        directory = workspace.absolute(path)
        if style.name(directory) == "SKILL.md":
            directory = style.parent(directory)
        if file:
            return await self._read_skill_file(ctx, directory, file)

        manifest = style.join(directory, "SKILL.md")
        data = await self._read_workspace_file(workspace, manifest, MAX_MANIFEST_BYTES)
        skill, problem = parse_skill(data.decode("utf-8", errors="replace"), directory)
        if skill is None:
            raise ToolError(f"{manifest} 不是有效的技能：{problem}", code="invalid_skill")
        return skill_text(skill, directory)

    async def _read_skill_file(self, ctx: Any, directory: str, file: str) -> str:
        workspace = await self._workspace(ctx)
        if workspace is None:
            raise ToolError("当前会话未配置工作区", code="no_workspace")

        style = workspace.style
        target = style.join(directory, file)
        if style.is_absolute(file) or style.same(target, directory) or not style.inside(target, directory):
            raise ToolError("file 须为技能目录内的相对路径", code="invalid_arguments")

        data = await self._read_workspace_file(workspace, target, MAX_REFERENCE_BYTES)
        return data.decode("utf-8", errors="replace")

    @staticmethod
    async def _read_workspace_file(workspace: Any, path: str, limit: int) -> bytes:
        try:
            return await workspace.files.read_file(path, limit)
        except FileNotFoundError:
            raise ToolError(f"文件不存在：{path}", code="not_found") from None
        except PermissionError:
            raise ToolError(f"沙箱规则不允许读取 {path}", code="not_readable") from None
        except ValueError as error:
            raise ToolError(str(error), code="too_large") from None

    async def _place_and_describe(self, ctx: Any, skill: Skill) -> str:
        try:
            workspace = await ctx.resource("workspace")
        except Exception as error:
            return skill_text(skill, None, note=strings.NOTE_WORKSPACE_UNAVAILABLE.format(error=error))

        if workspace is None:
            return skill_text(skill, None, note=strings.NOTE_NO_WORKSPACE)

        try:
            location = await self.placement.place(workspace, skill)
        except ToolError:
            raise
        except Exception as error:
            return skill_text(skill, None, note=strings.NOTE_WORKSPACE_UNAVAILABLE.format(error=error))

        return skill_text(skill, location, note=strings.NOTE_READ_ONLY)

    async def selected_skill_text(self, ctx: Any, name: str) -> str | None:
        """返回用户指定技能的正文；技能不存在或无法读取时返回 None（在 before_turn 中调用，不应使本轮失败）。"""
        try:
            found = self.find(name)
            if found is not None:
                return await self._place_and_describe(ctx, found[1])
            skill = await self._workspace_skill(ctx, name)
        except ToolError as error:
            logger.warning("用户指定的技能 %s 无法加载：%s", name, error)
            return None

        if skill is not None:
            return skill_text(skill, skill.source_dir, note=strings.NOTE_WORKSPACE_SKILL)
        return None
