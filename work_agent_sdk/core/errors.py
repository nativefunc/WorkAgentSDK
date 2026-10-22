from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorInfo(BaseModel):
    """一轮以错误结束或被拒绝时的错误信息。source 取值为 model、tool、hook 或 internal。"""

    code: str
    message: str
    source: str = "internal"
    retryable: bool = False
    data: Any = None


class ToolError(Exception):
    """工具中可预期的失败。message 返回给模型，code 和 data 提供给前端。"""

    def __init__(self, message: str, *, code: str | None = None, data: Any = None, end_turn: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.data = data
        self.end_turn = end_turn


class ConfigError(ValueError):
    """配置错误，在创建 Agent、Runner 或会话时直接抛给开发者。"""


class NodeOffline(Exception):
    """节点无法连接。"""

    def __init__(self, name: str, detail: str = "") -> None:
        super().__init__(f"节点 {name} 当前离线{f'：{detail}' if detail else ''}")
        self.name = name


class RequestClosed(Exception):
    """答复的请求已不在等待状态。"""

    def __init__(self, request_id: str, status: str | None = None) -> None:
        super().__init__(f"请求 {request_id} 已不在等待答复{f'（{status}）' if status else ''}")
        self.request_id = request_id
        self.status = status


class SessionClosed(Exception):
    """向已关闭的会话发送消息或答复。"""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"会话 {session_id} 已关闭")
        self.session_id = session_id


class InvalidAnswer(ValueError):
    """答复不符合请求的 answer_schema；请求继续等待。"""


class TurnRejected(Exception):
    def __init__(self, info: ErrorInfo) -> None:
        super().__init__(info.message)
        self.info = info


class TurnFailed(Exception):
    def __init__(self, info: ErrorInfo) -> None:
        super().__init__(info.message)
        self.info = info


class HookFailed(Exception):
    def __init__(self, hook: str, point: str, error: BaseException) -> None:
        super().__init__(f"钩子 {hook}.{point} 执行出错：{type(error).__name__}: {error}")
        self.hook = hook
        self.point = point
        self.error = error
