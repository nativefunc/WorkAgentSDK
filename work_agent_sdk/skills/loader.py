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
        return None, "The file doesn't start with a YAML header (--- ... ---)"

    try:
        front_matter = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as error:
        return None, f"Failed to parse YAML: {error}"

    if not isinstance(front_matter, dict):
        return None, "The YAML header is not a key-value mapping"

    name = str(front_matter.get("name") or "").strip()
    description = str(front_matter.get("description") or "").strip()
    if not name or not description:
        return None, "Missing name or description"
    if len(name) > 64 or not SKILL_NAME.match(name):
        return None, f"name {name!r} is invalid; only lowercase letters, digits and hyphens are allowed, up to 64 characters"
    if len(description) > 1024:
        return None, "description exceeds the 1024-character limit"

    folder = re.split(r"[\\/]", directory.rstrip("\\/"))[-1]  # The directory may be on the backend or on the workspace's node, so both separators must be recognized
    if folder and folder != name:
        logger.warning("Skill directory name %s doesn't match name %s", folder, name)

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
            logger.warning("Skill directory does not exist: %s", self.path)
            return skills

        for name in sorted(os.listdir(self.path)):
            folder = os.path.join(self.path, name)
            manifest = os.path.join(folder, "SKILL.md")
            if not os.path.isfile(manifest):
                continue

            with open(manifest, encoding="utf-8") as file:
                skill, problem = parse_skill(file.read(), folder)

            if skill is None:
                logger.warning("Skipped skill %s: %s", folder, problem)
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
    # roots are configured by the developer, not chosen by the model, so read the node directly without the sandbox; the real path is still required to be inside the workspace
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
                logger.warning("Skipped skill %s: %s", directory, problem)
            entries[directory] = (fingerprint, skill)
        else:
            # It changed again between two looks and no content was obtained this time: look again next turn
            complete = False

    scan = WorkspaceScan(found["digest"] if complete else None, entries)
    return scan.skills, scan


def read_reference(directory: str, file: str) -> str:
    root = os.path.realpath(directory)
    target = os.path.realpath(os.path.join(root, file))
    if os.path.commonpath([root, target]) != root:
        raise ToolError("file must be a relative path inside the skill directory", code="invalid_arguments")
    if not os.path.isfile(target):
        raise ToolError(f"File {file} doesn't exist in the skill", code="not_found")
    if os.path.getsize(target) > MAX_REFERENCE_BYTES:
        raise ToolError(f"{file} exceeds the size limit", code="too_large")

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
