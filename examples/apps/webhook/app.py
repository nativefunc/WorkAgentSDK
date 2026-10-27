import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from work_agent_sdk import Agent, CustomMessage, Runner
from work_agent_sdk.models import OpenAI

agent = Agent(
    "ci-assistant",
    model=OpenAI("gpt-5"),
    instructions="You follow up on the repository's CI builds. When you receive a build failure notification, analyze likely causes from the log and suggest fixes.",
)

repo_sessions: dict[str, str] = {}
build_messages: dict[str, str] = {}


async def session_for(runner: Runner, repo: str):
    if repo not in repo_sessions:
        session = await runner.new_session(metadata={"repo": repo})
        repo_sessions[repo] = session.id
    return await runner.session(repo_sessions[repo])


async def handle_build(runner: Runner, event: dict) -> None:
    session = await session_for(runner, event["repo"])
    build_id = event["build_id"]

    if event["state"] == "started":
        message = await session.add_message(
            CustomMessage(
                "ci_build",
                data={"build_id": build_id, "progress": 0},
                status="in_progress",
            )
        )
        build_messages[build_id] = message.id
    elif event["state"] == "running":
        await session.update_message(
            build_messages[build_id],
            data={"build_id": build_id, "progress": event["progress"]},
        )
    elif event["state"] == "succeeded":
        await session.complete_message(
            build_messages.pop(build_id),
            data={"build_id": build_id, "progress": 100},
            for_model=f"Build #{build_id} passed.",
        )
    elif event["state"] == "failed":
        if build_id in build_messages:
            await session.complete_message(
                build_messages.pop(build_id),
                status="failed",
                data={"build_id": build_id},
            )

        alert = CustomMessage(
            "ci_failed",
            data=event,
            for_model=f"Build #{build_id} failed. End of log:\n{event['log']}",
        )
        await session.send(alert, priority=10).queued()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with Runner(agents=[agent]) as runner:
        app.state.runner = runner
        yield


app = FastAPI(lifespan=lifespan)


@app.post("/webhooks/ci")
async def ci_webhook(request: Request):
    body = await request.body()
    expected = hmac.new(os.environ["CI_WEBHOOK_SECRET"].encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("x-signature", "")):
        raise HTTPException(401)

    await handle_build(app.state.runner, json.loads(body))
    return {"ok": True}
