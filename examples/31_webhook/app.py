"""接入外部 webhook：把外部系统的事件作为 CustomMessage 告诉智能体。

本例接收 CI 系统的构建通知，每个仓库对应一个会话：
- 构建开始：add_message 添加一条进行中的消息，前端可以显示进度，模型暂时看不到
- 构建进行中：update_message 更新进度
- 构建成功：complete_message 结束消息，模型在下一次调用时看到结果，不开始新的一轮
- 构建失败：结束消息，并用 send(CustomMessage) 让智能体立即开始一轮分析原因

运行：
    pip install fastapi uvicorn
    export CI_WEBHOOK_SECRET=...
    uvicorn app:app --port 8000

模拟一次通知：
    body='{"repo": "acme/shop", "build_id": "123", "state": "failed", "log": "test_login FAILED"}'
    sig=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$CI_WEBHOOK_SECRET" | cut -d' ' -f2)
    curl -X POST http://127.0.0.1:8000/webhooks/ci -H "x-signature: $sig" -d "$body"
"""

import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from work_agent_sdk import Agent, CustomMessage, Runner
from work_agent_sdk.models import Claude

agent = Agent(
    "ci-assistant",
    model=Claude("claude-sonnet-4-5"),
    instructions="你负责跟进仓库的 CI 构建。收到构建失败的通知时，根据日志分析可能的原因并给出修复建议。",
)

# 仓库 -> 会话 id、构建 id -> 消息 id。实际项目中保存在数据库里
repo_sessions: dict[str, str] = {}
build_messages: dict[str, str] = {}


async def session_for(runner: Runner, repo: str):
    if repo not in repo_sessions:
        session = await runner.new_session(metadata={"repo": repo})
        repo_sessions[repo] = session.id
    return await runner.session(repo_sessions[repo])


async def handle_ci_event(runner: Runner, event: dict) -> None:
    session = await session_for(runner, event["repo"])
    build_id = event["build_id"]

    if event["state"] == "started":
        message = await session.add_message(
            CustomMessage("ci.build", data={"build_id": build_id, "progress": 0}, status="in_progress")
        )
        build_messages[build_id] = message.id

    elif event["state"] == "running":
        await session.update_message(
            build_messages[build_id], data={"build_id": build_id, "progress": event["progress"]}
        )

    elif event["state"] == "succeeded":
        await session.complete_message(
            build_messages.pop(build_id),
            data={"build_id": build_id, "progress": 100},
            for_model=f"构建 #{build_id} 通过。",
        )

    elif event["state"] == "failed":
        if build_id in build_messages:
            await session.complete_message(
                build_messages.pop(build_id), status="failed", data={"build_id": build_id}, for_model=None
            )
        # 让智能体立即处理：和用户消息一样开始一轮；priority 让它排在其他排队消息之前
        alert = CustomMessage(
            "ci.failed",
            data=event,
            for_model=f"构建 #{build_id} 失败。日志末尾：\n{event['log']}",
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

    # 立即返回，智能体的输出通过会话的事件推送给前端（见 30_web_backend）
    await handle_ci_event(request.app.state.runner, json.loads(body))
    return {"ok": True}
