from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
from typing import Any

from work_agent_sdk.core.errors import ToolError
from work_agent_sdk.host.files.scan import tree_hash
from work_agent_sdk.skills.loader import Skill, files_in

logger = logging.getLogger("work_agent_sdk")


class Placement:
    def __init__(self) -> None:
        self._placing: dict[tuple[str, str], asyncio.Lock] = {}

    async def place(self, workspace: Any, skill: Skill) -> str:
        content_hash = await asyncio.to_thread(tree_hash, skill.source_dir)

        # Skills are placed in the node's data directory by the framework, not as a model action, so operate on the node directly (bypassing the workspace sandbox)
        node = workspace.node
        await node.make_dir(workspace.skills_dir)
        skills_dir = (await node.stat(workspace.skills_dir)).real_path
        destination = workspace.style.join(skills_dir, f"{skill.name}-{content_hash[:16]}")
        key = (workspace.node_name, destination)
        async with self._placing.setdefault(key, asyncio.Lock()):
            existing = await node.tree_hash(destination)
            if existing == content_hash:
                return destination

            if existing is not None:
                logger.warning("Contents of skill directory %s don't match %s; placing it again", destination, skill.source_dir)
                await node.remove(destination)

            await self._copy(node, workspace.style, skill.source_dir, destination)

            if await node.tree_hash(destination) != content_hash:
                raise ToolError(f"Skill {skill.name} failed verification after placement", code="skill_unavailable")

        return destination

    async def _copy(self, node: Any, style: Any, source: str, destination: str) -> None:
        # Write to a temporary directory first and then rename it as a whole, so the target directory either doesn't exist or is complete
        partial = f"{destination}.partial-{uuid.uuid4().hex[:8]}"
        try:
            for path in await asyncio.to_thread(files_in, source):
                relative = os.path.relpath(
                    path, source
                )  # Relative path on the backend; when joined to the target node's path, the target node's path style is used
                with open(path, "rb") as file:
                    data = file.read()
                await node.write_file(
                    style.join(partial, *relative.split(os.sep)), data, executable=os.access(path, os.X_OK)
                )

            await node.move(partial, destination)
        except Exception as error:
            with contextlib.suppress(Exception):
                await node.remove(partial)
            try:
                # Another backend process may have placed the same skill at the same time
                await node.stat(style.join(destination, "SKILL.md"))
            except Exception:
                raise ToolError(f"Failed to place skill: {error}", code="skill_unavailable") from None
