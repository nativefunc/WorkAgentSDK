from __future__ import annotations

import asyncio
from typing import Annotated, Any

from pydantic import Field

import work_agent_sdk.strings.computer as strings
from work_agent_sdk.computer.actions import COMPUTER, from_openai
from work_agent_sdk.computer.requests import AppAccess
from work_agent_sdk.computer.service import BoundComputer, ComputerService, apps_text, authorized_apps
from work_agent_sdk.core.coordinates import model_space
from work_agent_sdk.core.errors import ToolError
from work_agent_sdk.core.messages import MediaPart, TextPart, ToolResult
from work_agent_sdk.core.requests import Takeover
from work_agent_sdk.core.tool import Context, Tool, Toolset
from work_agent_sdk.host.screen.actions import POINT_FIELDS
from work_agent_sdk.host.screen.apps import find_app
from work_agent_sdk.host.screen.executor import fit_within
from work_agent_sdk.host.screen.policy import (
    ComputerMode,
    SystemKeys,
    app_id,
    default_tier,
    matches,
    safe_app_name,
    tier_of,
)


class MemberTool(Tool):
    def __init__(self, owner: ComputerUse, member: str) -> None:
        super().__init__(
            None,
            name=f"computer_{member}",
            description=COMPUTER[member].description,
            input_schema=COMPUTER[member].schema,
            annotations={"read_only": COMPUTER[member].read_only, "destructive": not COMPUTER[member].read_only},
            native=("computer", member),
        )
        self.owner = owner
        self.member = member

    async def run(self, context: Context, args: dict[str, Any]) -> ToolResult:
        try:
            return await self.owner.perform(context, [(self.member, dict(args))])
        except (KeyError, TypeError, ValueError) as error:
            raise ToolError(f"Invalid arguments: {error}", code="invalid_arguments") from None


class BatchTool(Tool):
    def __init__(self, owner: ComputerUse) -> None:
        super().__init__(
            None,
            name="computer_actions",  # Named computer_<member> like the single-action tools; here the member is actions
            description=strings.BATCH_DESCRIPTION,
            input_schema={
                "type": "object",
                "properties": {"actions": {"type": "array", "items": {"type": "object"}}},
                "required": ["actions"],
            },
            annotations={"destructive": True},
            native=("computer", "actions"),
        )
        self.owner = owner

    async def run(self, context: Context, args: dict[str, Any]) -> ToolResult:
        try:
            actions = [from_openai(action) for action in args.get("actions") or []]
        except (KeyError, TypeError, ValueError) as error:
            raise ToolError(f"Invalid arguments: {error}", code="invalid_arguments") from None
        if not actions or actions[-1][0] != "screenshot":
            actions.append(("screenshot", {}))
        return await self.owner.perform(context, actions)


class ComputerUse(Toolset):
    """Computer toolset. Provided when the session is configured with a computer (new_session(computer=...))."""

    name = "computer"
    description = "Operate the session's computer"
    needs = (ComputerService,)
    requires = frozenset({"computer"})

    def __init__(
        self,
        *,
        max_size: tuple[int, int] = (1280, 800),
        screenshot_after_action: bool = True,
        takeover: bool = True,
    ) -> None:
        super().__init__()
        self.max_size = tuple(max_size)
        self.takeover = takeover
        self._takeover = Tool(
            self._request_takeover,
            name="computer_takeover",
            description=strings.TAKEOVER_DESCRIPTION,
            annotations={"read_only": True, "interactive": True},
        )
        self.screenshot_after_action = screenshot_after_action
        self._members = [MemberTool(self, member) for member in COMPUTER.names]
        self._batch = BatchTool(self)
        self._access = Tool(
            self._request_access,
            name="computer_request_access",
            description=strings.REQUEST_ACCESS_DESCRIPTION,
            annotations={"interactive": True},
        )
        self._list = Tool(
            self._list_apps,
            name="computer_list_apps",
            description=strings.LIST_APPS_DESCRIPTION,
            annotations={"read_only": True},
        )
        self._open = Tool(
            self._open_app,
            name="computer_open_app",
            description=strings.OPEN_APP_DESCRIPTION,
            annotations={"read_only": False, "destructive": False},
        )

    def __repr__(self) -> str:
        return "ComputerUse()"

    async def tools(self, context: Context) -> list[Tool]:
        computer = await context.resource("computer")
        if computer is None:
            return []

        # OpenAI's native computer runs a batch of actions each time (computer_actions); other models run one action at a time.
        # Both tools are in the catalog (the other isn't sent to the model), so after switching models, calls of the other kind in the history can still run
        batch = context.model.action_batches("computer")
        tools: list[Tool] = [tool.copy(hidden=batch) for tool in self._members]
        tools.append(self._batch.copy(hidden=not batch))
        tools.append(self._open)

        if computer.policy.mode == ComputerMode.STANDARD:
            tools += [self._access, self._list]
        if self.takeover:
            tools.append(self._takeover)

        return tools

    def screenshot_limit(self, context: Context) -> tuple[int, int]:
        edge = context.model.max_image_edge
        return min(self.max_size[0], edge), min(self.max_size[1], edge)

    def _computer(self, context: Context) -> BoundComputer:
        if context.computer is None:
            raise ToolError("No computer is configured for this session", code="no_computer")
        return context.computer

    async def perform(self, context: Context, actions: list[tuple[str, dict[str, Any]]]) -> ToolResult:
        computer = self._computer(context)
        waited_for: str | None = None
        limit = self.screenshot_limit(context)
        real = await computer.size()
        view = fit_within(real, limit)

        # Ratio from the model's coordinate system to real screen pixels; for most models the coordinate system is the screenshot (view), for Qwen it is 1000×1000
        space = model_space(context.model, view)
        scale = (real[0] / space[0], real[1] / space[1])
        notes: list[str] = []
        image: bytes | None = None
        zoomed = False
        changed = False
        for member, args in actions:
            # Acquire control before each action: if the user takes over midway, a batch stops between two actions
            waited_for = waited_for or await computer.claim()

            if member == "screenshot":
                image, view = await computer.screenshot(max_size=limit)
                real = computer.real_size or real
                space = model_space(context.model, view)
                scale = (real[0] / space[0], real[1] / space[1])
                zoomed = False
                continue

            if member == "zoom":
                image = await self._zoom(computer, args["region"], scale, limit)
                zoomed = True
                continue

            real_args = dict(args)
            for field in POINT_FIELDS:
                if real_args.get(field) is not None:
                    x, y = real_args[field]
                    real_args[field] = [round(float(x) * scale[0]), round(float(y) * scale[1])]

            try:
                result = await computer.act(member, real_args)
            except PermissionError as error:
                raise ToolError(str(error), code="not_allowed") from None

            if member == "cursor_position" and result:
                x, y = round(result["x"] / scale[0]), round(result["y"] / scale[1])
                notes.append(strings.CURSOR_POSITION.format(x=x, y=y))

            changed = changed or not COMPUTER[member].read_only
            image = None
            zoomed = False

        if image is None and changed and self.screenshot_after_action:
            await asyncio.sleep(0.3)
            await computer.claim()
            image, view = await computer.screenshot(max_size=limit)
            space = model_space(context.model, view)

        user_acted = await computer.take_user_acted()
        content: list[Any] = []
        text = "; ".join(notes) if notes else strings.DONE
        data: dict[str, Any] = {"actions": [member for member, _ in actions], "size": list(view)}

        if image is not None:
            content.append(MediaPart.image_bytes(image))
            if not notes and not zoomed:
                text = strings.SCREENSHOT.format(width=space[0], height=space[1])

        if waited_for is not None:
            text = strings.WAITED_FOR + text
        if user_acted:
            text = strings.USER_ACTED + text

        return ToolResult(content=[TextPart(text=text), *content], data=data)

    async def _zoom(
        self, computer: BoundComputer, region: list[int], scale: tuple[float, float], limit: tuple[int, int]
    ) -> bytes:
        if not isinstance(region, list) or len(region) != 4:
            raise ToolError("zoom is missing the region argument, formatted as [x0, y0, x1, y1]", code="invalid_arguments")

        box = (
            round(region[0] * scale[0]),
            round(region[1] * scale[1]),
            round(region[2] * scale[0]),
            round(region[3] * scale[1]),
        )
        try:
            image, _ = await computer.screenshot(max_size=limit, region=box)
        except ValueError as error:
            raise ToolError(str(error), code="invalid_arguments") from None

        return image

    async def _request_access(
        self,
        ctx: Context,
        apps: Annotated[list[str], Field(description=strings.ACCESS_APPS)],
        reason: Annotated[str, Field(description=strings.ACCESS_REASON)],
        system_keys: Annotated[bool, Field(description=strings.ACCESS_SYSTEM_KEYS)] = False,
    ) -> str:
        computer = self._computer(ctx)
        policy = computer.policy
        grants = await computer.grants()
        wanted, missing, refused = _classify_apps(apps, await computer.apps(installed=True), policy, grants)
        lines = []
        if refused:
            lines.append(strings.ACCESS_REFUSED.format(apps=", ".join(refused)))
        if missing:
            lines.append(strings.ACCESS_MISSING.format(apps=", ".join(missing)))

        needs_keys = system_keys and policy.system_keys == SystemKeys.ASK and not grants.get("system_keys")
        if not wanted and not needs_keys:
            lines.append(strings.ACCESS_ALREADY_GRANTED if apps else strings.ACCESS_NOTHING)
            return "\n".join(lines)

        answer = await ctx.wait_for(AppAccess(reason=reason, apps=wanted, system_keys=needs_keys))
        if not answer.approved:
            lines.append(strings.ACCESS_DENIED.format(note=f": {answer.note}" if answer.note else ""))
            return "\n".join(lines)

        tiers: dict[str, Any] = {}
        names: dict[str, str] = {}
        for app in wanted:
            for key in (app["id"], app["exe"]):
                if key:
                    tiers[key] = app["tier"]
                    names[key] = app["name"]

        await ctx.step("grant", lambda: computer.grant(tiers, system_keys=needs_keys, names=names))
        granted = apps_text([[app["name"], app["tier"]] for app in wanted]) if wanted else strings.SYSTEM_KEYS
        lines.append(strings.ACCESS_GRANTED.format(granted=granted))
        return "\n".join(lines)

    async def _open_app(self, ctx: Context, app: Annotated[str, Field(description=strings.OPEN_APP_APP)]) -> ToolResult:
        computer = self._computer(ctx)
        waited_for = await computer.claim()

        try:
            opened = await computer.open_app(app)
        except PermissionError as error:
            raise ToolError(str(error), code="not_allowed") from None
        except LookupError as error:
            raise ToolError(str(error), code="not_found") from None
        except RuntimeError as error:
            raise ToolError(str(error), code="open_failed") from None

        await asyncio.sleep(0.3)
        await computer.claim()
        limit = self.screenshot_limit(ctx)
        image, view = await computer.screenshot(max_size=limit)
        text = strings.APP_OPENED.format(app=safe_app_name(opened.get("name")))
        if waited_for is not None:
            text = strings.WAITED_FOR + text
        if await computer.take_user_acted():
            text = strings.USER_ACTED + text

        data = {"app": {"id": opened.get("id"), "name": safe_app_name(opened.get("name"))}, "size": list(view)}
        return ToolResult(content=[TextPart(text=text), MediaPart.image_bytes(image)], data=data)

    async def _request_takeover(
        self, ctx: Context, reason: Annotated[str, Field(description=strings.TAKEOVER_REASON)]
    ) -> dict[str, Any]:
        computer = self._computer(ctx)
        answer = await ctx.wait_for(Takeover(reason=reason, target="computer", node=computer.config.node))

        # The user is done: end the takeover (if the user didn't call release_control) and the agent continues
        await computer.release_control()
        result = answer.model_dump()
        if answer.done:
            result["note_for_you"] = strings.TAKEOVER_DONE
        else:
            note = strings.TAKEOVER_NOTE.format(note=answer.note) if answer.note else ""
            result["note_for_you"] = strings.TAKEOVER_NOT_DONE.format(note=note)
        return result

    async def _list_apps(self, ctx: Context) -> str:
        computer = self._computer(ctx)
        policy = computer.policy
        grants = await computer.grants()
        lines = [
            strings.APPS_AUTHORIZED.format(apps=apps_text(authorized_apps(policy, grants, await computer.ceiling())))
        ]
        if grants.get("system_keys"):
            lines.append(strings.APPS_SYSTEM_KEYS)

        running = await computer.apps()
        if running:
            names = ", ".join(dict.fromkeys(safe_app_name(app.get("name")) for app in running))
            lines.append(strings.APPS_RUNNING.format(apps=names))

        frontmost = await computer.frontmost()
        if frontmost:
            lines.append(strings.APPS_FRONTMOST.format(app=safe_app_name(frontmost.get("name"))))

        return "\n".join(lines)


def _classify_apps(
    names: list[str], apps: list[dict[str, Any]], policy: Any, grants: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    wanted: list[dict[str, Any]] = []
    missing: list[str] = []
    refused: list[str] = []
    for name in names:
        found = find_app(name, apps)
        if found is None:
            missing.append(safe_app_name(name))
        elif matches(found, policy.deny):
            refused.append(safe_app_name(found.get("name")))
        elif tier_of(policy, found, grants) is None:
            tier = policy.allow.get(app_id(found)) or default_tier(policy, found)
            wanted.append(
                {
                    "id": app_id(found),
                    "name": safe_app_name(found.get("name")),
                    "exe": str(found.get("exe") or ""),
                    "tier": tier,
                    "warning": strings.TIER_WARNINGS.get(tier, ""),
                }
            )

    return wanted, missing, refused
