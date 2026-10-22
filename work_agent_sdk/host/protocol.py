from __future__ import annotations

import builtins
import errno
from typing import Annotated, Any, ClassVar

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    ValidationError,  # noqa: F401  转出供守护进程捕获，使其无需直接依赖 pydantic
)

from work_agent_sdk.host.files.helper import TRANSFER_PREFIX
from work_agent_sdk.host.screen.actions import summarize_action

PROTOCOL_VERSION = 9

# 流编号由后端生成，设备只拿它作内存中的键。限定字符与长度，防止异常的后端借它越界
StreamId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]

# 未带 errno 的内置 OSError 子类（如 raise FileNotFoundError(path)）对应的 errno，还原时据此得到同一子类
OS_ERRNO = {
    FileNotFoundError: "ENOENT",
    FileExistsError: "EEXIST",
    PermissionError: "EACCES",
    IsADirectoryError: "EISDIR",
    NotADirectoryError: "ENOTDIR",
    TimeoutError: "ETIMEDOUT",
    ProcessLookupError: "ESRCH",
    ChildProcessError: "ECHILD",
    InterruptedError: "EINTR",
    BlockingIOError: "EAGAIN",
    BrokenPipeError: "EPIPE",
    ConnectionRefusedError: "ECONNREFUSED",
    ConnectionResetError: "ECONNRESET",
    ConnectionAbortedError: "ECONNABORTED",
}
# 不能由设备指定的异常：会改变后端的控制流（迭代提前结束）
UNSAFE = (StopIteration, StopAsyncIteration)


def error_info(error: BaseException) -> dict[str, Any]:
    # errno 带上符号形式：两端系统不同时数值可能不同
    base = next(cls for cls in type(error).__mro__ if cls.__module__ == "builtins")
    info: dict[str, Any] = {"type": base.__name__, "message": str(error)}
    if isinstance(error, KeyError) and error.args:
        info["message"] = str(error.args[0])  # str(KeyError) 带引号，还原时会再加一层

    if isinstance(error, OSError):
        number = error.errno if isinstance(error.errno, int) else None
        name = errno.errorcode.get(number) if number is not None else None
        if name is None:
            name = next((OS_ERRNO[cls] for cls in type(error).__mro__ if cls in OS_ERRNO), None)

        info["errno"] = name

    return info


def remote_error(info: dict[str, Any]) -> Exception:
    message = str(info.get("message", ""))
    cls = getattr(builtins, str(info.get("type", "")), None)
    if not (isinstance(cls, type) and issubclass(cls, Exception)) or issubclass(cls, UNSAFE):
        return RuntimeError(message)

    if issubclass(cls, OSError):
        number = getattr(errno, str(info.get("errno") or ""), None)
        if isinstance(number, int):
            # 由 errno 得到 Python 对应的子类（ENOENT → FileNotFoundError；ENOSPC 等仍为 OSError）
            cls = type(OSError(number, ""))

        error = cls(message)
        error.errno = number if isinstance(number, int) else None
        return error

    # 个别内置异常的构造参数不止一个（如 UnicodeDecodeError）：改用其可以只传消息的基类（ValueError）
    for candidate in cls.__mro__:
        try:
            return candidate(message)
        except TypeError:
            continue

    return RuntimeError(message)


MAX_BLOCK = 4 * 1024 * 1024


def is_transfer_file(path: str) -> bool:
    return path.replace("\\", "/").rsplit("/", 1)[-1].startswith(TRANSFER_PREFIX)


class Call(BaseModel):
    op: ClassVar[str]

    def arguments(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def audit(self) -> dict[str, Any] | None:
        return None


# 文件操作在设备审计日志中记录的路径参数；不在其中的操作（查看信息、列出目录）不记录
FILE_AUDIT = {
    "make_dir": ("path", None),
    "remove": ("path", None),
    "delete": ("path", None),
    "move": ("source", "target"),
    "copy": ("source", "target"),
    "snapshot": ("source", None),
    "commit": ("target", None),
}
# 记录中显示的操作名称：snapshot 为读取文件，commit 为写入文件
FILE_AUDIT_NAMES = {"snapshot": "read", "commit": "write"}


class FileOp(Call):
    op = "file"
    file_op: str
    arguments_: dict[str, Any] = {}

    def arguments(self) -> dict[str, Any]:
        return {"file_op": self.file_op, "arguments": self.arguments_}

    @classmethod
    def parse(cls, arguments: dict[str, Any]) -> FileOp:
        return cls(file_op=arguments["file_op"], arguments_=arguments.get("arguments") or {})

    def audit(self) -> dict[str, Any] | None:
        fields = FILE_AUDIT.get(self.file_op)
        if fields is None:
            return None

        path = str(self.arguments_.get(fields[0]))
        if self.file_op == "remove" and is_transfer_file(path):
            # 框架清理自身的传输文件
            return None

        record: dict[str, Any] = {"event": "file", "op": FILE_AUDIT_NAMES.get(self.file_op, self.file_op), "path": path}
        if fields[1] is not None:
            record["target"] = self.arguments_.get(fields[1])

        return record


class ReadBlock(Call):
    op = "read_block"
    path: str
    offset: int
    size: int


class WriteBlock(Call):
    op = "write_block"
    path: str
    offset: int
    # base64
    data: str


class TreeHashCall(Call):
    op = "tree_hash"
    path: str


class FindManifests(Call):
    op = "find_manifests"
    workspace: str
    roots: list[str]
    manifest: str
    max_size: int
    unchanged: str | None = None
    read: list[str] = []


class ComputerCall(Call):
    op = "computer"
    display: str | None = None
    computer_op: str
    arguments_: dict[str, Any] = {}

    def arguments(self) -> dict[str, Any]:
        return {"display": self.display, "computer_op": self.computer_op, "arguments": self.arguments_}

    @classmethod
    def parse(cls, arguments: dict[str, Any]) -> ComputerCall:
        return cls(
            display=arguments.get("display"),
            computer_op=arguments["computer_op"],
            arguments_=arguments.get("arguments") or {},
        )

    def audit(self) -> dict[str, Any] | None:
        inner = self.arguments_
        if self.computer_op == "screenshot":
            if "unless_hash" in inner:
                # 实时画面每秒多帧，设备按时间合并为一条审计记录
                return {"event": "screen", "action": "watch"}
            return {"event": "screen", "action": "screenshot", "region": inner.get("region")}
        if self.computer_op == "user_act":
            action = str(inner.get("action"))
            return {
                "event": "screen",
                "action": action,
                "source": "user",
                **summarize_action(action, inner.get("args") or {}),
            }
        if self.computer_op == "act":
            action = str(inner.get("action"))
            return {
                "event": "screen",
                "action": action,
                "session": inner.get("session"),
                **summarize_action(action, inner.get("args") or {}),
            }
        return None


class BrowserStart(Call):
    op = "browser_start"
    options: dict[str, Any]

    def audit(self) -> dict[str, Any] | None:
        return {"event": "browser_start", "profile": self.options.get("profile")}


class BrowserStop(Call):
    op = "browser_stop"
    profile: str

    def audit(self) -> dict[str, Any] | None:
        return {"event": "browser_stop", "profile": self.profile}


CALLS: dict[str, type[Call]] = {
    kind.op: kind
    for kind in (
        FileOp,
        ReadBlock,
        WriteBlock,
        TreeHashCall,
        FindManifests,
        ComputerCall,
        BrowserStart,
        BrowserStop,
    )
}


def parse_call(op: str, arguments: dict[str, Any]) -> Call:
    kind = CALLS.get(op)
    if kind is None:
        raise ValueError(f"未知的操作：{op}")
    if kind is ComputerCall:
        return ComputerCall.parse(arguments)
    if kind is FileOp:
        return FileOp.parse(arguments)
    return kind.model_validate(arguments)


# 后端发给设备的控制消息，先按模型校验再处理；不合法时断开本次连接，不改动任何状态


class Inbound(BaseModel):
    type: ClassVar[str]


class CommandStart(Inbound):
    type = "command"
    id: StreamId
    command: dict[str, Any]
    stdin: bool = False


class StdinData(Inbound):
    type = "stdin"
    id: StreamId
    offset: int = Field(ge=0)
    data: str  # base64


class StdinClose(Inbound):
    type = "stdin_close"
    id: StreamId
    total: int = Field(ge=0)  # 输入的总字节数，设备据此判断是否已收齐


class Ack(Inbound):
    type = "ack"
    id: StreamId
    received: int = Field(ge=0)


class Cancel(Inbound):
    type = "cancel"
    id: StreamId


class TcpOpen(Inbound):
    type = "tcp_open"
    id: StreamId
    port: int = Field(ge=1, le=65535)


class TcpData(Inbound):
    type = "tcp_data"
    id: StreamId
    data: str  # base64


class TcpClose(Inbound):
    type = "tcp_close"
    id: StreamId


INBOUND: dict[str, type[Inbound]] = {
    message.type: message for message in (CommandStart, StdinData, StdinClose, Ack, Cancel, TcpOpen, TcpData, TcpClose)
}


def parse_inbound(message: dict[str, Any]) -> Inbound | None:
    # 未知类型返回 None，便于向后兼容
    kind = INBOUND.get(str(message.get("type")))
    if kind is None:
        return None
    return kind.model_validate(message)
