from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

import work_agent_sdk.strings.browser as strings
from work_agent_sdk.browser.actions import BROWSER
from work_agent_sdk.browser.driver.pages import PageError, SensitiveInputError
from work_agent_sdk.browser.service import BoundBrowser, BrowserService
from work_agent_sdk.core.actions import BROWSER_STATE
from work_agent_sdk.core.coordinates import model_space
from work_agent_sdk.core.errors import ToolError
from work_agent_sdk.core.messages import MediaPart, TextPart, ToolResult
from work_agent_sdk.core.requests import Approval, Takeover
from work_agent_sdk.core.tool import Context, Tool, Toolset
from work_agent_sdk.core.untrusted import wrap_web


class MemberTool(Tool):
    def __init__(self, owner: BrowserUse, member: str) -> None:
        action = BROWSER[member]
        read_only = action.read_only
        super().__init__(
            None,
            name=f"browser_{member}",
            description=action.description,
            input_schema=action.schema,
            annotations={"read_only": read_only, "destructive": not read_only, "open_world": True},
            native=("browser", member),
        )
        self.owner = owner
        self.member = member

    async def run(self, context: Context, args: dict[str, Any]) -> ToolResult:
        return await self.owner.perform(context, self.member, dict(args))


class BrowserUse(Toolset):
    """Browser toolset. Provided when the session is configured with a browser (new_session(browser=...))."""

    name = "browser"
    description = "Operate the session's browser"
    needs = (BrowserService,)
    requires = frozenset({"browser"})

    def __init__(self, *, takeover: bool = True) -> None:
        super().__init__()
        self.takeover = takeover
        self._members = {member: MemberTool(self, member) for member in BROWSER.names}
        self._takeover = Tool(
            self._request_takeover,
            name="browser_takeover",
            description=strings.TAKEOVER_DESCRIPTION,
            annotations={"read_only": True, "interactive": True},
        )

    def __repr__(self) -> str:
        return "BrowserUse()"

    async def tools(self, context: Context) -> list[Tool]:
        browser = await context.resource("browser")
        if browser is None:
            return []

        tools: list[Tool] = [tool for member, tool in self._members.items() if browser.policy.enabled(member)]
        if self.takeover:
            tools.append(self._takeover)

        return tools

    def _browser(self, context: Context) -> BoundBrowser:
        if context.browser is None:
            raise ToolError("No browser is configured for this session", code="no_browser")
        return context.browser

    async def perform(self, context: Context, member: str, args: dict[str, Any]) -> ToolResult:
        browser = self._browser(context)
        if browser.paused():
            raise ToolError(strings.PAUSED, code="paused")
        if not browser.policy.enabled(member):
            raise ToolError(f"browser_{member} is not enabled", code="not_allowed")
        if member in browser.policy.confirm:
            await self._confirm(context, member, args)

        result = await self._run(browser, member, args, takeover=self.takeover)
        if member == "screenshot":
            space = model_space(context.model, await browser.viewport(args.get("tab_id")))
            result = {**result, "text": strings.SCREENSHOT.format(width=space[0], height=space[1])}

        pages = await browser.browser_context()
        state = await pages.with_titles(pages.state(browser.owner))
        content = _result_content(
            result, state, blocked=len(pages.take_blocked()), reconnected=pages.take_reconnected(browser.owner)
        )
        return ToolResult(content=content, data={"member": member, BROWSER_STATE: state})

    @staticmethod
    async def _confirm(context: Context, member: str, args: dict[str, Any]) -> None:
        detail: dict[str, Any] = {
            "member": member,
            "args": {key: value for key, value in args.items() if key != "text"},
        }
        if member == "javascript_exec":
            detail["code"] = str(args.get("text", ""))[:4000]

        answer = await context.wait_for(Approval(title=f"Browser: {BROWSER[member].description}", detail=detail))
        if not answer.approved:
            note = f": {answer.note}" if answer.note else ""
            raise ToolError(f"The user didn't approve this action{note}", code="denied")

    @staticmethod
    async def _run(browser: BoundBrowser, member: str, args: dict[str, Any], *, takeover: bool) -> dict[str, Any]:
        try:
            return await browser.perform(member, args)
        except ToolError:
            raise
        except SensitiveInputError as error:
            if error.kind == "focus":
                text = strings.SENSITIVE_FOCUS_TAKEOVER if takeover else strings.SENSITIVE_FOCUS_USER
            else:
                text = strings.SENSITIVE_FIELD_TAKEOVER if takeover else strings.SENSITIVE_FIELD_USER
            raise ToolError(text, code="not_allowed") from None
        except PermissionError as error:
            raise ToolError(str(error), code="not_allowed") from None
        except (KeyError, TypeError, ValueError) as error:
            raise ToolError(f"Invalid arguments: {error}", code="invalid_arguments") from None
        except PageError as error:
            raise ToolError(str(error), code="browser_error") from None
        except Exception as error:
            # After the device pauses, the browser connection is dropped and the lower layer only reports a connection failure
            if browser.paused():
                raise ToolError(strings.PAUSED, code="paused") from None
            message = str(error).splitlines()[0][:300] if str(error) else type(error).__name__
            raise ToolError(f"Browser error: {message}", code="browser_error") from None

    async def _request_takeover(
        self, ctx: Context, reason: Annotated[str, Field(description=strings.TAKEOVER_REASON)]
    ) -> dict[str, Any]:
        browser = self._browser(ctx)
        context = await browser.browser_context()
        tab = await context.tab(browser.owner)
        answer = await ctx.wait_for(
            Takeover(
                reason=reason,
                target="browser",
                node=browser.node,
                tab_id=tab.id,
                url=tab.page.url,
            )
        )
        result = answer.model_dump()
        if answer.done:
            result["note_for_you"] = strings.TAKEOVER_DONE
        else:
            note = strings.TAKEOVER_NOTE.format(note=answer.note) if answer.note else ""
            result["note_for_you"] = strings.TAKEOVER_NOT_DONE.format(note=note)
        return result


def _result_content(result: dict[str, Any], state: dict[str, Any], *, blocked: int, reconnected: bool) -> list[Any]:
    notes = []
    if reconnected:
        notes.append(strings.RECONNECTED)
    if blocked:
        notes.append(strings.REQUESTS_BLOCKED.format(count=blocked))

    touched = sorted(
        {change["tab_id"] for change in state.get("state_changes", []) if change.get("type") == "user_input"}
    )
    if touched:
        notes.append(strings.USER_ACTED.format(tabs=", ".join(touched)))

    text = result.get("text") or ""
    if result.get("untrusted") and text:
        text = wrap_web(text)

    content: list[Any] = []
    if notes:
        content.append(TextPart(text="\n".join(notes)))
    if text:
        content.append(TextPart(text=text))

    image = result.get("image")
    if image is not None:
        content.append(MediaPart.image_bytes(image))
    if not content:
        content.append(TextPart(text=strings.DONE))

    return content


__all__ = ["BrowserUse"]
