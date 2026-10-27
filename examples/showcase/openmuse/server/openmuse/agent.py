from __future__ import annotations

import datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from work_agent_sdk import (
    Agent,
    Approval,
    BrowserUse,
    ComputerUse,
    CustomMessage,
    Deny,
    Hooks,
    Request,
    Scheduler,
    Shell,
    Tool,
    ToolError,
    Toolset,
    ViewImage,
    tool,
)
from work_agent_sdk.models import OpenAICompatible, Qwen

from openmuse.config import Settings
from openmuse.db import User
from openmuse.files import guess_mime, save_upload
from openmuse.nodes import online as node_online
from openmuse.state import app_state


async def user_of(ctx: Any) -> User | None:
    db = app_state().db
    chat = db.chat(ctx.root_id)
    if chat is not None:
        return db.user(chat.user_id)
    info = await ctx.session.info()
    user_id = info.metadata.get("user_id")
    return db.user(int(user_id)) if user_id is not None else None


class AskOption(BaseModel):
    label: Annotated[str, Field(description="Option text, short, e.g. \"Saturday morning\"")]
    description: Annotated[str, Field(description="Optional extra explanation, one sentence")] = ""


class AskUser(Request):
    question: str
    options: list[AskOption]
    multi_select: bool = False
    allow_other: bool = True

    class Answer(BaseModel):
        selected: list[str] = Field(default_factory=list)
        other: str = ""


@tool(
    description=(
        "Ask the user a question with 2 to 6 options to tap. Use it when the user needs to decide between options or add preferences, "
        "or to confirm before an action with consequences (buying, sending, deleting, booking). Don't use it for small talk; don't ask about things you can decide yourself."
    ),
    annotations={"interactive": True, "read_only": True},
)
async def ask_user(
    ctx,
    question: Annotated[str, Field(description="The question, one sentence stating clearly what the user needs to decide")],
    options: Annotated[list[AskOption], Field(min_length=2, max_length=6, description="Options")],
    multi_select: Annotated[bool, Field(description="Whether multiple options can be selected")] = False,
) -> str:
    answer = await ctx.wait_for(AskUser(question=question, options=options, multi_select=multi_select))
    labels = {option.label for option in options}
    chosen = [label for label in answer.selected if label in labels]
    if not multi_select:
        chosen = chosen[:1]

    parts = []
    if chosen:
        parts.append("The user chose: " + ", ".join(chosen))
    if answer.other.strip():
        parts.append("The user added: " + answer.other.strip())
    return "; ".join(parts) if parts else "The user didn't choose any option"


MAX_SHARE_BYTES = 20 * 1024 * 1024


@tool(
    description=(
        "Share a file in the workspace with the user. The file appears in the conversation and the user can open or download it. "
        "Use it for results such as reports, screenshots and exported spreadsheets."
    ),
    requires=["workspace"],
)
async def share_file(
    ctx,
    path: Annotated[str, Field(description="Path of the file relative to the workspace, e.g. reports/weekly.md")],
    caption: Annotated[str, Field(description="Optional one-sentence caption")] = "",
) -> str:
    user = await user_of(ctx)
    if user is None:
        raise ToolError("Couldn't find the session's user", code="no_user")

    try:
        info = await ctx.workspace.files.stat(path)
        if info.is_dir:
            raise ToolError(f"{path} is a directory; package it into a single file first", code="not_a_file")
        if info.size > MAX_SHARE_BYTES:
            raise ToolError(f"{path} is larger than 20 MB and can't be shared", code="too_large")
        data = await ctx.workspace.files.read_file(path, MAX_SHARE_BYTES)
    except FileNotFoundError:
        raise ToolError(f"File not found: {path}", code="not_found") from None
    except PermissionError:
        raise ToolError(f"No permission to read {path}", code="not_readable") from None

    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    saved = await ctx.step(
        "save", lambda: save_upload(user.id, name, data, chat_id=ctx.root_id, mime=guess_mime(name, data))
    )
    await ctx.add_message(
        CustomMessage(
            "openmuse.file",
            data={**saved, "caption": caption, "path": path},
            for_model=f"Shared file {path}.",
        )
    )
    return f"Shared {name}"


class Gate(Toolset):
    def __init__(self, inner: Toolset, resource: str) -> None:
        self.inner = inner
        self.resource = resource
        self.name = inner.name
        self.description = inner.description
        self.needs = inner.needs
        self.requires = inner.requires
        self.hooks = list(inner.hooks)
        self.agents = list(getattr(inner, "agents", []) or [])

    def __repr__(self) -> str:
        return f"Gate({self.inner!r}, {self.resource!r})"

    async def tools(self, ctx: Any) -> list[Tool]:
        user = await user_of(ctx)
        if user is None or not user.settings.get(self.resource, True):
            return []
        return await self.inner.tools(ctx)

    def __getattr__(self, attribute: str) -> Any:
        return getattr(self.inner, attribute)


SUBMITTING = frozenset({"browser_left_click", "browser_double_click", "browser_triple_click", "browser_key"})


class Safety(Hooks):
    async def before_tool(self, ctx, call):
        if call.name != "shell" and call.name not in SUBMITTING:
            return None

        user = await user_of(ctx)
        if user is None:
            return Deny("Couldn't find the session's user")

        if call.name == "shell":
            if not user.settings.get("confirm_shell"):
                return None
            answer = await ctx.wait_for(
                Approval(title="Run this command in the workspace?", detail={"command": call.args.get("command", "")})
            )
            if not answer.approved:
                return Deny("The user didn't approve running this command" + (f": {answer.note}" if answer.note else ""))
            return None

        if not user.settings.get("confirm_submit", True) or not ctx.has_resource("browser"):
            return None
        try:
            target = await ctx.browser.targets(call)
        except Exception:
            return None
        if not target.get("submits"):
            return None

        host = target.get("host") or "the website"
        answer = await ctx.wait_for(
            Approval(
                title=f"Submit the form on {host}?",
                detail={"page": (target.get("page") or {}).get("url"), "submits_to": target.get("url")},
            )
        )
        if not answer.approved:
            return Deny("The user didn't approve submitting this form" + (f": {answer.note}" if answer.note else ""))
        return None

INSTRUCTIONS = """\
You are {app}, {name}'s personal assistant. You use the workspace, browser and computer to complete tasks for the user.

## Environment

- Current time: {now} ({timezone})

## Rules

- When the workspace, browser or computer is unavailable, ask the user to connect a device under Profile → Computer in the app, or turn it on in the permissions page.
- When a password is needed, ask the user to take over; never ask the user to provide a password in the conversation.
- Save generated files in the workspace, and share files meant for the user with share_file.
- After finishing a task, briefly report the result, and include URLs when citing web pages.
- Answer in the language the user uses.
"""


async def instructions(ctx: Any) -> str:
    user = await user_of(ctx)
    tz = ZoneInfo(app_state().settings.timezone)
    now = datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M %A")
    name = user.name if user is not None else "the user"
    return INSTRUCTIONS.format(app="OpenMuse", name=name, now=now, timezone=tz.key)

def make_model(settings: Settings) -> Any:
    if settings.model_api == "compatible":
        return OpenAICompatible(
            settings.model,
            base_url=settings.compatible_base_url,
            api_key="${DASHSCOPE_API_KEY}",
            thinking_format="enable_thinking",
            screen_coordinates=(1000, 1000),
        )

    return Qwen(settings.model, base_url=settings.dashscope_base_url, input_types=("text", "image"))


def build_agent(settings: Settings, model: Any) -> Agent:
    files = Toolset(
        "files",
        tools=[ViewImage(), share_file],
        description="View images, share files",
        requires=["workspace"],
    )
    return Agent(
        "openmuse",
        model=model,
        instructions=instructions,
        thinking=settings.thinking,
        tools=[
            ask_user,
            Gate(Shell(timeout=30), "workspace"),
            Gate(files, "workspace"),
            Gate(BrowserUse(), "browser"),
            Gate(ComputerUse(), "computer"),
            Scheduler(timezone=settings.timezone),
        ],
        hooks=[Safety()],
        max_steps=80,
    )
