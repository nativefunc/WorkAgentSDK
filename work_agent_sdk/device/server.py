from __future__ import annotations

import asyncio
import base64
import contextlib
import contextvars
import hashlib
import hmac
import importlib.util
import json
import logging
import os
import ssl
import sys
import time
import urllib.parse
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

import work_agent_sdk.host.browser as browser_process
import work_agent_sdk.host.files.helper as helper
import work_agent_sdk.host.files.scan as scan
import work_agent_sdk.host.protocol as protocol
from work_agent_sdk.device.audit import AuditLog
from work_agent_sdk.device.commands import DeviceCommands, encode_output
from work_agent_sdk.device.policy import DevicePolicy, FileRules
from work_agent_sdk.device.protect import PROTECT_TEMPLATES
from work_agent_sdk.host.browser import BrowserOptions
from work_agent_sdk.host.commands.run import local_shell
from work_agent_sdk.host.files.paths import local_system
from work_agent_sdk.host.protocol import PROTOCOL_VERSION
from work_agent_sdk.host.screen.apps import local_apps
from work_agent_sdk.host.screen.backends import default_display, local_screen
from work_agent_sdk.host.screen.executor import ScreenExecutor, start_escape_listener
from work_agent_sdk.host.screen.policy import DeviceCeiling
from work_agent_sdk.host.websocket import (
    WebSocket,
    accept_websocket,
    check_url,
    finish_handshake,
    is_loopback,
    refuse_handshake,
)

logger = logging.getLogger("work_agent_sdk.node")
# 屏幕动作作用的应用：执行端在动作前设置，审计日志在动作后记录（位于同一任务中）
_acted_app: contextvars.ContextVar[str | None] = contextvars.ContextVar("acted_app", default=None)

HEARTBEAT_INTERVAL = 15
# 超过该时间未收到后端的任何消息（后端会答复每次心跳），即视为连接已断开
HEARTBEAT_TIMEOUT = 45
# 单条消息的发送时限（与后端的 SEND_TIMEOUT 一致）。超时视为连接已坏：中止连接并重连，未确认的输出在重连后补发
SEND_TIMEOUT = 30
# 单条答复超过该大小时分段发送，避免单条消息超过 WebSocket 服务的大小上限
RESULT_PART_SIZE = 256 * 1024
RECONNECT_DELAYS = (1, 2, 5, 10, 30)
# 后端未告知宽限时间时使用的默认值；实际使用后端的宽限时间再加一段余量，确保后端仍在等待的命令在设备端一定存在
DEFAULT_GRACE = 60

# 实时画面（watch）的截图在审计日志中合并为一条记录的时间间隔
WATCH_AUDIT_INTERVAL = 60


class DeviceDaemon:
    def __init__(
        self,
        *,
        name: str,
        token: str,
        workspace: list[str] | None = None,
        protect: str = "standard",
        sandbox: str | None = None,
        network: bool | list[str] = True,
        allow_unsandboxed: bool = False,
        srt_binary: str = "srt",
        srt_nested: bool = False,
        srt_settings: dict[str, Any] | None = None,
        env: list[str] | None = None,
        screen: bool = False,
        screen_ceiling: DeviceCeiling | None = None,
        displays: list[str] | None = None,
        browser: bool = False,
        esc_stop: bool = False,
        grace: float | None = None,
        on_activity: Callable[[dict[str, Any]], Any] | None = None,
        audit_log: str | None = None,
    ) -> None:
        check_options(
            workspace=workspace,
            protect=protect,
            sandbox=sandbox,
            network=network,
            allow_unsandboxed=allow_unsandboxed,
            screen=screen,
            browser=browser,
        )
        self.name = name
        self.token = token
        self.policy = (
            DevicePolicy(
                roots=[os.path.realpath(os.path.expanduser(path)) for path in workspace or []],
                sandbox=sandbox or "none",
                network=network,
                allow_unsandboxed=allow_unsandboxed,
                protect=protect,
                srt_binary=srt_binary,
                srt_nested=srt_nested,
                srt_settings=dict(srt_settings or {}),
            )
            # 仅开放浏览器时同样需要：框架需在自身的下载目录中为下载文件改名（仅此一个目录）
            if workspace or browser
            else None
        )

        # 开放目录并不意味着可以执行命令：仅在指定 --sandbox 时可以
        self.commands_enabled = sandbox is not None
        self.screen_enabled = screen
        self.browser_enabled = browser
        self.ceiling = screen_ceiling or DeviceCeiling()

        # 开放的桌面（Linux X 桌面编号）。会话可在其中选择，省略时用第一块；其他系统只有一块桌面，记为 [None]
        self.displays = opened_displays(displays)
        self.esc_stop = esc_stop
        self.grace_override = grace
        self.grace = grace or DEFAULT_GRACE
        self.on_activity = on_activity

        # 除 PATH、HOME 等之外额外传递给命令的本机环境变量（只记录名称，值取自设备守护进程自身）
        self.env = list(env or [])
        self._send: Any = None
        # 中止当前连接（不等缓冲区发完），发送超时时调用
        self._abort: Any = None
        if self.policy is not None:
            helper.ensure_private_dir(self.policy.data_dir)

        self.commands = DeviceCommands(
            policy=self.policy,
            env=self.env,
            enabled=self.commands_enabled,
            grace=lambda: self.grace,
            post=self._post,
            spawn=self._spawn,
            audit=self._audit,
        )

        # 浏览器调试连接：后端发来的数据先进入队列（None 表示后端已关闭），连接浏览器后按顺序写入
        self._tunnels: dict[str, asyncio.Queue[bytes | None]] = {}
        self._executors: dict[str | None, ScreenExecutor] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._listener: Any = None
        self.paused: str | None = None  # 暂停原因；None 表示未暂停
        self.emergency_stopped = False  # 暂停是否由急停（Esc 或 emergency_stop）引起
        self._watch_audited: float = -WATCH_AUDIT_INTERVAL

        # 每次启动设备守护进程时重新生成，后端据此区分“同一设备重连”与“另一台机器使用了相同名称”
        self.instance_id = uuid.uuid4().hex
        self.audit = AuditLog(audit_log) if audit_log else None
        self._audit_started(network=network, allow_unsandboxed=allow_unsandboxed, sandbox=sandbox, grace=grace)

    def _audit_started(
        self, *, network: bool | list[str], allow_unsandboxed: bool, sandbox: str | None, grace: float | None
    ) -> None:
        commands = self.commands_enabled
        self._audit(
            "started",
            name=self.name,
            workspace=list(self.roots) or None,
            protect=self.policy.protect if self.policy is not None else None,
            sandbox=sandbox,
            network=network if commands else None,
            allow_unsandboxed=allow_unsandboxed if commands else None,
            env=self.env if commands else None,
            screen=self.screen_enabled,
            screen_ceiling=self.ceiling.model_dump(mode="json") if self.screen_enabled else None,
            displays=self.displays if self.screen_enabled or self.browser_enabled else None,
            esc_stop=self.esc_stop if self.screen_enabled else None,
            browser=self.browser_enabled,
            disconnect_grace=grace,
        )

    def _audit(self, event: str, **fields: Any) -> None:
        if self.audit is not None:
            self.audit.write(event, **fields)

    @property
    def roots(self) -> list[str]:
        return self.policy.roots if self.policy is not None else []

    def manifest(self) -> dict[str, Any]:
        workspace = None
        if self.policy is not None and self.roots:
            workspace = {
                "roots": [{"path": path} for path in self.roots],
                "protect": self.policy.protect,
                "sandbox": self.policy.node_sandbox.model_dump(mode="json") if self.commands_enabled else None,
            }

        return {
            "os": local_system(),
            "shell": local_shell(),
            "home": os.path.expanduser("~"),
            "workspace": workspace,
            "screen": self.screen_enabled,
            "screen_ceiling": self.ceiling.model_dump(mode="json") if self.screen_enabled else None,
            "displays": [display for display in self.displays if display] if self.screen_enabled else None,
            "browser": self.browser_enabled,
            "paused": bool(self.paused),
        }

    def register_message(self) -> dict[str, Any]:
        return {
            "type": "register",
            "version": PROTOCOL_VERSION,
            "name": self.name,
            "token": self.token,
            "instance": self.instance_id,
            "manifest": self.manifest(),
            # 重连时告知每条命令已收到的输入位置，后端据此从该位置重发输入
            "commands": self.commands.positions(),
        }

    def pause(self, reason: str = "设备所有者已暂停电脑操作") -> None:
        self.paused = reason
        self._audit("paused", reason=reason)

        for executor in self._executors.values():
            executor.pause(reason)

        self._report_state()

    def resume(self) -> None:
        self.paused = None
        self.emergency_stopped = False
        self._audit("resumed")

        for executor in self._executors.values():
            executor.resume()

        self._report_state()

    def emergency_stop(self, *, source: str = "owner") -> None:
        self.paused, self.emergency_stopped = "设备所有者已触发急停", True
        self._audit("emergency_stop", source=source)

        for executor in self._executors.values():
            executor.emergency_stop()

        self._report_state()

    def _report_state(self) -> None:
        if self._send is None:
            return
        with contextlib.suppress(RuntimeError):
            self._spawn(self._post({"type": "state", "manifest": {"paused": bool(self.paused)}}))

    def _spawn(self, work: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.get_running_loop().create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _executor(self, display: str | None) -> ScreenExecutor:
        executor = self._executors.get(display)
        if executor is None:
            executor = ScreenExecutor(
                local_screen(display), local_apps(display), ceiling=self.ceiling, on_activity=self._activity
            )
            if self.paused:
                executor.pause(self.paused)

            self._executors[display] = executor
            if self.esc_stop and self._listener is None:
                self._listener = start_escape_listener(self._escape_pressed)

        return executor

    def _escape_pressed(self) -> None:
        # 监听的是守护进程所在的桌面，框架刚向这块桌面发出键盘输入时，按键可能来自框架自身
        own = self._executors.get(default_display())
        if own is None or not own.sent_input_recently():
            self.emergency_stop(source="esc")

    def _activity(self, event: dict[str, Any]) -> None:
        if event.get("event") == "action":
            _acted_app.set(event.get("app"))
        if self.on_activity is not None:
            with contextlib.suppress(Exception):
                self.on_activity(event)

    async def run_forever(self, url: str) -> None:
        check_url(url)
        self._audit("connecting", url=_without_credentials(url))
        attempt = 0
        while True:
            socket = None
            try:
                socket = await WebSocket.connect(url)
                attempt = 0
                await self.serve(socket.send_text, socket.receive_text, socket.abort)
            except PermissionError:
                raise
            except Exception as error:
                logger.warning("与后端的连接已断开：%s", error)
            finally:
                if socket is not None:
                    await socket.close()

            delay = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

    async def listen(self, host: str, port: int, *, tls_cert: str | None = None, tls_key: str | None = None) -> None:
        context = None
        if tls_cert:
            context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            context.load_cert_chain(tls_cert, tls_key)
        elif not is_loopback(host):
            raise PermissionError("监听非回环地址时须提供 --tls-cert 和 --tls-key")

        active = asyncio.Lock()
        expected = hashlib.sha256(self.token.encode()).hexdigest()

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            accepted = await accept_websocket(reader, writer)
            if accepted is None:
                return

            socket, headers = accepted
            given = headers.get("authorization", "")
            given = given[7:] if given.lower().startswith("bearer ") else ""
            peer = writer.get_extra_info("peername")
            peer = f"{peer[0]}:{peer[1]}" if isinstance(peer, tuple) else None
            if not hmac.compare_digest(hashlib.sha256(given.encode()).hexdigest(), expected):
                logger.warning("已拒绝一个令牌无效的连接")
                self._audit("connection_refused", peer=peer, reason="令牌无效")
                await refuse_handshake(socket)
                return
            if active.locked():
                self._audit("connection_refused", peer=peer, reason="已有后端连接")
                await refuse_handshake(socket, "409 Conflict")
                return

            async with active:
                await finish_handshake(socket, headers)
                try:
                    await self.serve(socket.send_text, socket.receive_text, socket.abort)
                except Exception as error:
                    logger.warning("与后端的连接已断开：%s", error)
                finally:
                    await socket.close()

        server = await asyncio.start_server(handle, host, port, ssl=context)
        logger.info("正在 %s:%s 等待后端连接", host, port)
        self._audit("listening", address=f"{host}:{port}", tls=bool(tls_cert))

        async with server:
            await server.serve_forever()

    async def serve(self, send: Any, receive: Any, abort: Any = None) -> None:
        if self.policy is not None:
            # 清理此前中断的传输遗留的传输文件（只清理长时间未改动的）
            await asyncio.to_thread(helper.clean_transfers, os.path.join(self.policy.data_dir, "tmp"))

        await send(json.dumps(self.register_message(), ensure_ascii=False))
        reply = json.loads(await receive())
        if reply.get("type") != "registered":
            self._audit("register_refused", reason=reply.get("reason"))
            if reply.get("retry"):
                raise ConnectionError(f"后端暂不接受连接：{reply.get('reason')}")
            raise PermissionError(f"后端拒绝了本设备：{reply.get('reason')}")

        if self.grace_override is None and reply.get("grace"):
            self.grace = float(reply["grace"])

        logger.info("已连接到后端，设备名 %s", self.name)
        self._audit("connected")
        self._send = send
        self._abort = abort
        self.commands.connected()
        await self.commands.resume(reply.get("resume") or {})
        heartbeat = asyncio.create_task(self._heartbeat())
        reason = None
        try:
            while True:
                try:
                    text = await asyncio.wait_for(receive(), HEARTBEAT_TIMEOUT)
                except TimeoutError:
                    raise ConnectionError(f"{HEARTBEAT_TIMEOUT} 秒内未收到后端的消息") from None
                self._dispatch(json.loads(text))
        except BaseException as error:
            reason = str(error) or type(error).__name__
            raise
        finally:
            self._audit("disconnected", reason=reason)
            heartbeat.cancel()
            self._send = None
            self._abort = None
            for queue in self._tunnels.values():
                queue.put_nowait(None)

            self._tunnels.clear()

            self.commands.disconnected()

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            await self._post({"type": "ping"})

    async def _post(self, message: dict[str, Any]) -> bool:
        send, abort = self._send, self._abort
        if send is None:
            return False

        try:
            await asyncio.wait_for(send(json.dumps(message, ensure_ascii=False)), SEND_TIMEOUT)
        except TimeoutError:
            # 连接半死时写入会一直卡在 drain() 上，直到 TCP 超时（十几分钟），期间命令也随之卡住
            logger.warning("向后端发送消息 %s 秒未完成，断开连接后重连", SEND_TIMEOUT)
            if self._send is send:
                self._send = None
                if abort is not None:
                    abort()
            return False
        except Exception:
            return False

        return True

    def _dispatch(self, message: dict[str, Any]) -> None:
        # 控制消息不合法时直接抛出，由收发循环断开连接，不改动任何状态
        if message.get("type") == "call":
            self._spawn(self._handle_call(message))
            return

        try:
            parsed = protocol.parse_inbound(message)
        except protocol.ValidationError as error:
            problem = error.errors()[0].get("msg") if error.errors() else str(error)
            raise ValueError(f"消息 {message.get('type')!r} 的字段不合法：{problem}") from None

        if parsed is None:
            return  # 未知类型（如 pong）忽略，便于协议向后兼容

        if isinstance(parsed, protocol.CommandStart):
            self.commands.start(parsed)
        elif isinstance(parsed, protocol.StdinData):
            self.commands.stdin(parsed)
        elif isinstance(parsed, protocol.StdinClose):
            self.commands.stdin_close(parsed)
        elif isinstance(parsed, protocol.Ack):
            self.commands.acknowledge(parsed)
        elif isinstance(parsed, protocol.Cancel):
            self.commands.cancel(parsed)
        elif isinstance(parsed, protocol.TcpOpen):
            # 立即登记：连接浏览器需要时间，期间到达的数据不能丢失
            self._tunnels[parsed.id] = asyncio.Queue()
            self._spawn(self._tunnel(parsed.id, parsed.port, self._tunnels[parsed.id]))
        elif isinstance(parsed, protocol.TcpData):
            if parsed.id in self._tunnels:
                self._tunnels[parsed.id].put_nowait(base64.b64decode(parsed.data))
        elif isinstance(parsed, protocol.TcpClose):
            if parsed.id in self._tunnels:
                self._tunnels.pop(parsed.id).put_nowait(None)

    async def _handle_call(self, message: dict[str, Any]) -> None:
        call_id = message["id"]
        try:
            value = await self._run_call(message["op"], message.get("arguments") or {})
        except Exception as error:
            error_info = protocol.error_info(error)
            await self._post({"type": "result", "id": call_id, "error": error_info})
            return

        # 较大的结果（截图、读取文件）分段发送，最后一条 result 注明总段数
        text = json.dumps(value, ensure_ascii=False)
        parts = [text[start : start + RESULT_PART_SIZE] for start in range(0, len(text), RESULT_PART_SIZE)]
        for part in parts[:-1]:
            await self._post({"type": "result_part", "id": call_id, "data": part})

        await self._post({"type": "result", "id": call_id, "json": parts[-1] if parts else "null"})

    def _workspace(self) -> DevicePolicy:
        if self.policy is None:
            raise PermissionError("该设备未开放工作区")
        return self.policy

    def _file_rules(self) -> FileRules:
        return FileRules(self._workspace())

    def _readable(self, path: str) -> str:
        real = os.path.realpath(os.path.expanduser(path))
        self._file_rules().check_read(real)
        return real

    async def _run_call(self, op: str, arguments: dict[str, Any]) -> Any:
        call = protocol.parse_call(op, arguments)
        handler = self._handlers[type(call)]
        record = call.audit() if self.audit is not None else None
        if record is not None and record.get("action") == "watch":
            # 实时画面每秒多帧：同一段观看在审计日志中每分钟记录一条
            now = time.monotonic()
            if now - self._watch_audited < WATCH_AUDIT_INTERVAL:
                record = None
            else:
                self._watch_audited = now

        if record is None:
            return await handler(call)

        event = record.pop("event")
        _acted_app.set(None)

        try:
            value = await handler(call)
        except PermissionError as error:
            self._audit(event, **record, app=_acted_app.get(), outcome="denied", reason=str(error))
            raise
        except Exception as error:
            self._audit(event, **record, app=_acted_app.get(), outcome="error", reason=str(error))
            raise

        self._audit(event, **record, app=_acted_app.get(), outcome="ok")
        return value

    @property
    def _handlers(self) -> dict[type[protocol.Call], Any]:
        return {
            protocol.FileOp: self._file_op,
            protocol.ReadBlock: self._read_block,
            protocol.WriteBlock: self._write_block,
            protocol.TreeHashCall: self._tree_hash,
            protocol.FindManifests: self._find_manifests,
            protocol.ComputerCall: self._computer,
            protocol.BrowserStart: self._browser_start,
            protocol.BrowserStop: self._browser_stop,
        }

    async def _file_op(self, call: protocol.FileOp) -> Any:
        return await asyncio.to_thread(helper.run_op, call.file_op, call.arguments_, self._file_rules())

    async def _read_block(self, call: protocol.ReadBlock) -> Any:
        size = min(call.size, protocol.MAX_BLOCK)
        data = await asyncio.to_thread(helper.read_block, self._file_rules(), call.path, call.offset, size)
        return encode_output(data)

    async def _write_block(self, call: protocol.WriteBlock) -> None:
        data = base64.b64decode(call.data)
        await asyncio.to_thread(helper.write_block, self._file_rules(), call.path, call.offset, data)

    async def _tree_hash(self, call: protocol.TreeHashCall) -> str | None:
        # 先检查权限再判断是否存在，以免后端借此探测设备上任意路径是否存在
        path = self._readable(call.path)
        if not os.path.exists(path):
            return None
        # 目录中的每一项（包括符号链接指向的位置）同样按开放的目录检查
        return await asyncio.to_thread(scan.tree_hash, path, self._readable)

    async def _find_manifests(self, call: protocol.FindManifests) -> Any:
        return await asyncio.to_thread(
            scan.find_manifests,
            call.workspace,
            call.roots,
            call.manifest,
            call.max_size,
            unchanged=call.unchanged,
            read=call.read,
            readable=self._readable,
        )

    async def _computer(self, call: protocol.ComputerCall) -> Any:
        if not self.screen_enabled:
            raise PermissionError("该设备未开放屏幕")
        return await self._executor(self._display(call.display)).handle(call.computer_op, call.arguments_)

    def _display(self, requested: str | None) -> str | None:
        if requested is None:
            return self.displays[0]
        if requested not in self.displays:
            if self.displays == [None]:
                raise PermissionError(f"该设备只有一块桌面，不能指定桌面 {requested}")
            raise PermissionError(f"该设备未开放桌面 {requested}；开放的桌面为 {'、'.join(map(str, self.displays))}")
        return requested

    async def _browser_start(self, call: protocol.BrowserStart) -> int:
        if not self.browser_enabled:
            raise PermissionError("该设备未开放浏览器")
        if self.paused:
            raise PermissionError(self.paused)

        options = BrowserOptions.model_validate(call.options)
        if options.executable:
            raise PermissionError("设备上的浏览器由设备守护进程自行查找，不允许指定可执行文件")

        browser_process.check_safe_args(options.args)

        # 有界面的浏览器显示在设备所有者开放的第一块桌面上，不由后端指定
        options = options.model_copy(update={"display": None if options.headless else self.displays[0]})
        return await browser_process.start_browser(options)

    async def _browser_stop(self, call: protocol.BrowserStop) -> None:
        if not self.browser_enabled:
            raise PermissionError("该设备未开放浏览器")
        await browser_process.stop_browser(call.profile)

    # 浏览器调试连接：只能连接到本设备上由框架启动的浏览器
    async def _allowed_port(self, port: int) -> bool:
        return self.browser_enabled and not self.paused and port in await browser_process.framework_ports()

    async def _tunnel(self, stream_id: str, port: int, incoming: asyncio.Queue[bytes | None]) -> None:
        allowed = await self._allowed_port(port)
        self._audit("browser_connect", port=port, outcome="ok" if allowed else "denied")

        if not allowed:
            self._tunnels.pop(stream_id, None)
            await self._post({"type": "tcp_close", "id": stream_id, "reason": "设备不允许连接该端口"})
            return

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            self._tunnels.pop(stream_id, None)
            await self._post({"type": "tcp_close", "id": stream_id})
            return

        async def downstream() -> None:
            while (data := await incoming.get()) is not None:
                writer.write(data)
                await writer.drain()
            writer.close()

        writing = asyncio.create_task(downstream())
        try:
            while data := await reader.read(65536):
                if not await self._post({"type": "tcp_data", "id": stream_id, "data": encode_output(data)}):
                    break
        finally:
            writing.cancel()
            self._tunnels.pop(stream_id, None)
            writer.close()
            await self._post({"type": "tcp_close", "id": stream_id})


def _without_credentials(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"

    netloc = f"{host}:{parts.port}" if parts.port else host
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def check_options(
    *,
    workspace: list[str] | None,
    protect: str,
    sandbox: str | None,
    network: bool | list[str],
    allow_unsandboxed: bool,
    screen: bool,
    browser: bool,
) -> None:
    if protect not in PROTECT_TEMPLATES:
        raise ValueError(f"--protect 的取值 {protect!r} 无效；可选值为 {' 或 '.join(PROTECT_TEMPLATES)}")

    if sandbox is not None:
        if not workspace:
            raise ValueError("--sandbox 仅用于在开放目录中执行命令；请同时使用 --workspace 指定开放目录")
        if sandbox not in ("srt", "none"):
            raise ValueError(f"--sandbox 的取值 {sandbox!r} 无效；可选值为 srt 或 none")
        if sandbox == "srt" and not isinstance(network, list):
            raise ValueError("--sandbox srt 需要明确网络范围；请用 --network 列出允许访问的域名，不允许联网时传空值")

    if allow_unsandboxed and sandbox is None:
        raise ValueError("--allow-unsandboxed 需要与 --sandbox 同时使用；未指定 --sandbox 时不允许执行命令")
    if not (workspace or screen or browser):
        raise ValueError("未开放任何能力；请至少指定 --workspace、--screen 或 --browser 之一")
    if screen and importlib.util.find_spec("PIL") is None:
        # 截图在设备端完成缩放和裁剪后再回传
        raise ValueError("开放屏幕需要 Pillow；请执行 pip install Pillow pyautogui")


def opened_displays(displays: list[str] | None) -> list[str | None]:
    if not sys.platform.startswith("linux"):
        if displays:
            raise ValueError("--display 仅适用于 Linux")
        return [None]

    unique: list[str | None] = list(dict.fromkeys(display.strip() for display in displays or [] if display.strip()))
    return unique or [default_display()]
