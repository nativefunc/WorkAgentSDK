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
            # Listing skills is just an incidental notice; skip it if the workspace errors, without affecting the turn
            logger.warning("Can't read the workspace to list its skills: %s", error)
            return None

        if workspace is None:
            return None

        try:
            skills = await self.owner.current_workspace_skills(workspace)
        except Exception as error:
            logger.warning("Can't list skills in the workspace: %s", error)
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

        await ctx.add_message(
            CustomMessage(
                "skills.available",
                data=listed,
                display=False,
                for_model=text,
            )
        )
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
    description = "Load skills on demand"

    def __init__(self, *sources: str, workspace_roots: Sequence[str] = DEFAULT_WORKSPACE_ROOTS) -> None:
        """sources are skill directories on the backend; workspace_roots are skill directories on the workspace's own node; pass () to not use them."""
        self.directories = [SkillDirectory(path) for path in sources]
        self.workspace_roots = tuple(workspace_roots)

        # Last scan results of the workspace's own skills (per bound workspace), so only changed SKILL.md files are read; released when the binding becomes invalid
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
            raise ToolError(f"The workspace is currently unavailable: {error}", code="workspace_unavailable") from None

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
            raise ToolError(f"The workspace is currently unavailable: {error}", code="workspace_unavailable") from None

    async def _describe(self, ctx: Any) -> str:
        lines = [strings.LOAD_SKILL_DESCRIPTION]

        # Only list skills on the backend: the workspace's own skills get a separate skills.available message, to avoid connecting to the node just to build the description
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
            raise ToolError("Provide exactly one of name and path", code="invalid_arguments")
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
        raise ToolError(f"Skill {name} doesn't exist; if the user gave a directory, load it with path", code="not_found")

    async def _load_from_path(self, ctx: Any, path: str, file: str | None) -> str:
        workspace = await self._workspace(ctx)
        if workspace is None:
            raise ToolError("No workspace is configured for this session, so skills can't be loaded by directory", code="no_workspace")

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
            raise ToolError(f"{manifest} is not a valid skill: {problem}", code="invalid_skill")
        return skill_text(skill, directory)

    async def _read_skill_file(self, ctx: Any, directory: str, file: str) -> str:
        workspace = await self._workspace(ctx)
        if workspace is None:
            raise ToolError("No workspace is configured for this session", code="no_workspace")

        style = workspace.style
        target = style.join(directory, file)
        if style.is_absolute(file) or style.same(target, directory) or not style.inside(target, directory):
            raise ToolError("file must be a relative path inside the skill directory", code="invalid_arguments")

        data = await self._read_workspace_file(workspace, target, MAX_REFERENCE_BYTES)
        return data.decode("utf-8", errors="replace")

    @staticmethod
    async def _read_workspace_file(workspace: Any, path: str, limit: int) -> bytes:
        try:
            return await workspace.files.read_file(path, limit)
        except FileNotFoundError:
            raise ToolError(f"File not found: {path}", code="not_found") from None
        except PermissionError:
            raise ToolError(f"Sandbox rules don't allow reading {path}", code="not_readable") from None
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
        """Return the body of a skill the user specified; None if the skill doesn't exist or can't be read (called in before_turn, so it shouldn't fail the turn)."""
        try:
            found = self.find(name)
            if found is not None:
                return await self._place_and_describe(ctx, found[1])
            skill = await self._workspace_skill(ctx, name)
        except ToolError as error:
            logger.warning("Skill %s specified by the user can't be loaded: %s", name, error)
            return None

        if skill is not None:
            return skill_text(skill, skill.source_dir, note=strings.NOTE_WORKSPACE_SKILL)
        return None
