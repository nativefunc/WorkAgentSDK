from __future__ import annotations

import hashlib
import re
from typing import Any

from work_agent_sdk.core.messages import MediaPart, Message, ThinkingPart, UserMessage
from work_agent_sdk.core.untrusted import wrap_context
from work_agent_sdk.core.utils import new_id
from work_agent_sdk.models.base import Model

EFFORT_NAMES = {"max": "high"}


def as_user(message: Message) -> Message:
    if message.role != "custom":
        return message
    return UserMessage(id=message.id, text=wrap_context(message.kind, message.for_model or ""))


def is_same_model(message: Message, model: Model) -> bool:
    return bool(message.model) and message.model == model.id


def data_url(part: MediaPart) -> str:
    return f"data:{part.mime};base64,{part.data}"


def media_with_data(message: Message) -> list[MediaPart]:
    return [part for part in message.content if isinstance(part, MediaPart) and part.data]


def tool_result_text(message: Message) -> str:
    text = message.text
    if message.error:
        text = f"错误：{message.error}\n{text}".strip()
    return text or "（无输出）"


def unsupported_media_text(part: MediaPart) -> str:
    location = f" {part.path}" if part.path else ""
    return f"[{part.kind}{location}：该接口无法直接接收此类内容]"


def safe_call_id(call_id: str) -> str:
    # 改写时附加原 id 的哈希，避免不同的 id 改写后相同
    if not call_id:
        return new_id("call_")
    if re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", call_id):
        return call_id

    digest = hashlib.sha256(call_id.encode()).hexdigest()[:16]
    return re.sub(r"[^A-Za-z0-9_\-]", "_", call_id)[:47] + "_" + digest


def effort_name(thinking: str) -> str:
    return EFFORT_NAMES.get(thinking, thinking)


def history_thinking(message: Message, model: Model) -> list[tuple[ThinkingPart, bool]]:
    same_model = is_same_model(message, model)
    blocks = []
    for part in message.content:
        if not isinstance(part, ThinkingPart):
            continue
        if same_model and part.signature:
            blocks.append((part, True))
        elif part.text.strip() and not part.redacted:
            blocks.append((part, False))

    return blocks


def append_merged(items: list[dict[str, Any]], role: str, blocks: list[dict[str, Any]], key: str) -> None:
    # Anthropic 要求角色交替
    if not blocks:
        return
    if items and items[-1]["role"] == role:
        items[-1][key].extend(blocks)
    else:
        items.append({"role": role, key: blocks})
