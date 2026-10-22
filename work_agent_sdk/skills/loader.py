from __future__ import annotations

import logging
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import work_agent_sdk.strings.skills as strings
from work_agent_sdk.core.errors import ToolError
from work_agent_sdk.workspace.service import BoundWorkspace

logger = logging.getLogger("work_agent_sdk")

SKILL_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_REFERENCE_BYTES = 256 * 1024
FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)(.*)$", re.S)


@dataclass
class Skill:
    name: str
    description: str
    body: str
    source_dir: str
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)


def parse_skill(text: str, directory: str) -> tuple[Skill | None, str | None]:
    import yaml

    match = FRONT_MATTER.match(text)
    if not match:
        return None, "文件开头缺少 YAML 头部（--- ... ---）"

    try:
        front_matter = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as error:
        return None, f"YAML 解析失败：{error}"

    if not isinstance(front_matter, dict):
        return None, "YAML 头部不是键值映射"

    name = str(front_matter.get("name") or "").strip()
    description = str(front_matter.get("description") or "").strip()
    if not name or not description:
        return None, "缺少 name 或 description"
    if len(name) > 64 or not SKILL_NAME.match(name):
        return None, f"name {name!r} 不合规；仅允许小写字母、数字和连字符，最长 64 个字符"
    if len(description) > 1024:
        return None, "description 超过 1024 个字符的上限"

    folder = re.split(r"[\\/]", directory.rstrip("\\/"))[-1]  # 目录可能位于后端或工作区所在节点，两种分隔符均需识别
    if folder and folder != name:
        # 规范要求目录名与 name 一致；不一致时仅记录警告，技能仍可使用（下载的技能常被放入其他名称的目录）
        logger.warning("技能目录名 %s 与 name %s 不一致", folder, name)

    allowed = front_matter.get("allowed-tools") or []
    if isinstance(allowed, str):
        allowed = [item for item in allowed.split() if item]

    compatibility = front_matter.get("compatibility")
    metadata = front_matter.get("metadata")
    return (
        Skill(
            name=name,
            description=description,
            body=match.group(2).strip(),
            source_dir=directory,
            license=str(front_matter["license"]) if front_matter.get("license") else None,
            compatibility=str(compatibility).strip()[:500] if compatibility else None,
            metadata=metadata if isinstance(metadata, dict) else {},
            allowed_tools=[str(item) for item in allowed],
        ),
        None,
    )


def files_in(directory: str) -> list[str]:
    paths = []
    for root, directories, files in sorted(os.walk(directory)):
        directories.sort()
        paths += [os.path.join(root, name) for name in sorted(files)]
    return paths


class SkillDirectory:
    def __init__(self, path: str) -> None:
        self.path = os.path.abspath(os.path.expanduser(path))

    def __repr__(self) -> str:
        return f"SkillDirectory({self.path!r})"

    def list(self) -> dict[str, Skill]:
        skills: dict[str, Skill] = {}
        if not os.path.isdir(self.path):
            logger.warning("技能目录不存在：%s", self.path)
            return skills

        for name in sorted(os.listdir(self.path)):
            folder = os.path.join(self.path, name)
            manifest = os.path.join(folder, "SKILL.md")
            if not os.path.isfile(manifest):
                continue

            with open(manifest, encoding="utf-8") as file:
                skill, problem = parse_skill(file.read(), folder)

            if skill is None:
                logger.warning("已跳过技能 %s：%s", folder, problem)
                continue

            skills.setdefault(skill.name, skill)

        return skills


@dataclass
class WorkspaceScan:
    digest: str | None = None
    entries: dict[str, tuple[list[float], Skill | None]] = field(default_factory=dict)

    @property
    def skills(self) -> dict[str, Skill]:
        found: dict[str, Skill] = {}
        for _, skill in self.entries.values():
            if skill is not None:
                found.setdefault(skill.name, skill)
        return found


async def workspace_skills(
    workspace: BoundWorkspace, roots: Sequence[str], previous: WorkspaceScan | None = None
) -> tuple[dict[str, Skill], WorkspaceScan]:
    # roots 由开发者配置而非模型决定，所以直接读节点、不经过沙箱；仍要求真实路径在工作区内
    previous = previous or WorkspaceScan()
    node = workspace.node
    args = (workspace.path, [workspace.absolute(root) for root in roots], "SKILL.md", MAX_MANIFEST_BYTES)
    found = await node.find_manifests(*args, unchanged=previous.digest)
    if found["entries"] is None:
        return previous.skills, previous

    changed = [
        str(item["dir"])
        for item in found["entries"]
        if previous.entries.get(str(item["dir"]), (None, None))[0] != list(item["fingerprint"])
    ]
    if changed:
        found = await node.find_manifests(*args, read=changed)

    entries: dict[str, tuple[list[float], Skill | None]] = {}
    complete = True
    for item in found["entries"]:
        directory, fingerprint, text = str(item["dir"]), list(item["fingerprint"]), item["text"]
        old = previous.entries.get(directory)
        if old is not None and old[0] == fingerprint:
            entries[directory] = old
        elif text is not None:
            skill, problem = parse_skill(str(text), directory)
            if skill is None:
                logger.warning("已跳过技能 %s：%s", directory, problem)
            entries[directory] = (fingerprint, skill)
        else:
            # 两次查看之间又有变化，本次未取得内容：下一轮重新查看
            complete = False

    scan = WorkspaceScan(found["digest"] if complete else None, entries)
    return scan.skills, scan


def read_reference(directory: str, file: str) -> str:
    root = os.path.realpath(directory)
    target = os.path.realpath(os.path.join(root, file))
    if os.path.commonpath([root, target]) != root:
        raise ToolError("file 须为技能目录内的相对路径", code="invalid_arguments")
    if not os.path.isfile(target):
        raise ToolError(f"技能中不存在文件 {file}", code="not_found")
    if os.path.getsize(target) > MAX_REFERENCE_BYTES:
        raise ToolError(f"{file} 超过大小上限", code="too_large")

    with open(target, "rb") as handle:
        return handle.read().decode("utf-8", errors="replace")


def skill_text(skill: Skill, location: str | None, *, note: str = "") -> str:
    if location:
        head = strings.SKILL_WITH_FILES.format(name=skill.name, location=location, note=note)
    else:
        head = strings.SKILL_WITHOUT_FILES.format(name=skill.name, note=note)

    if skill.compatibility:
        head += strings.SKILL_COMPATIBILITY.format(compatibility=skill.compatibility)
    if skill.allowed_tools:
        head += strings.SKILL_ALLOWED_TOOLS.format(tools=" ".join(skill.allowed_tools))

    return f"{head}\n\n{skill.body}"
