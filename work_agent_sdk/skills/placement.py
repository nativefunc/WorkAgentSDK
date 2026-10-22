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

        # 技能由框架放置到节点的数据目录，不代表模型操作，因此直接操作节点（不经过工作区的沙箱）
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
                logger.warning("技能目录 %s 的内容与 %s 不一致，将重新放置", destination, skill.source_dir)
                await node.remove(destination)

            await self._copy(node, workspace.style, skill.source_dir, destination)

            if await node.tree_hash(destination) != content_hash:
                raise ToolError(f"技能 {skill.name} 放置后核对不一致", code="skill_unavailable")

        return destination

    async def _copy(self, node: Any, style: Any, source: str, destination: str) -> None:
        # 先写入临时目录再整体改名，保证目标目录要么不存在，要么内容完整
        partial = f"{destination}.partial-{uuid.uuid4().hex[:8]}"
        try:
            for path in await asyncio.to_thread(files_in, source):
                relative = os.path.relpath(
                    path, source
                )  # 后端上的相对路径；拼接到目标节点路径时按目标节点的路径风格处理
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
                # 其他后端进程可能已同时放置了同一技能
                await node.stat(style.join(destination, "SKILL.md"))
            except Exception:
                raise ToolError(f"放置技能失败：{error}", code="skill_unavailable") from None
