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
    refuse_handshake,
)

logger = logging.getLogger("work_agent_sdk.node")
# The app a screen action acts on: set by the executor before the action and recorded by the audit log after it (in the same task)
_acted_app: contextvars.ContextVar[str | None] = contextvars.ContextVar("acted_app", default=None)

HEARTBEAT_INTERVAL = 15
# If no message at all arrives from the backend within this time (the backend answers every heartbeat), the connection is considered dropped
HEARTBEAT_TIMEOUT = 45
# Send deadline for a single message (matches the backend's SEND_TIMEOUT). A timeout means the connection is broken: abort and reconnect; unacknowledged output is resent after reconnecting
SEND_TIMEOUT = 30
# Replies larger than this are sent in chunks, so a single message doesn't exceed the WebSocket server's size limit
RESULT_PART_SIZE = 256 * 1024
RECONNECT_DELAYS = (1, 2, 5, 10, 30)
# Default used when the backend doesn't announce a grace period; in practice the backend's grace period plus a margin is used, so commands the backend is still waiting on are guaranteed to exist on the device
DEFAULT_GRACE = 60

# Interval within which live view (watch) screenshots are merged into one audit log record
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
        network: list[str] | None = None,
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
            # Also needed when only the browser is exposed: the framework must rename downloaded files in its own download directory (that directory only)
            if workspace or browser
            else None
        )

        # Exposing directories doesn't mean commands can run: only when --sandbox is given
        self.commands_enabled = sandbox is not None
        self.screen_enabled = screen
        self.browser_enabled = browser
        self.ceiling = screen_ceiling or DeviceCeiling()

        # Exposed displays (Linux X display numbers). Sessions can choose among them, using the first when omitted; other OSes have a single display, recorded as [None]
        self.displays = opened_displays(displays)
        self.esc_stop = esc_stop
        self.grace_override = grace
        self.grace = grace or DEFAULT_GRACE
        self.on_activity = on_activity

        # Local environment variables passed to commands in addition to PATH, HOME etc. (only names are recorded; values come from the device daemon itself)
        self.env = list(env or [])
        self._send: Any = None
        # Abort the current connection (without waiting for the buffer to flush); called on send timeout
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

        # Browser debugging connections: data from the backend is queued first (None means the backend closed), then written in order once connected to the browser
        self._tunnels: dict[str, asyncio.Queue[bytes | None]] = {}
        self._executors: dict[str | None, ScreenExecutor] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._listener: Any = None
        self.paused: str | None = None  # Reason for pausing; None means not paused
        self.emergency_stopped = False  # Whether the pause was caused by an emergency stop (Esc or emergency_stop)
        self._watch_audited: float = -WATCH_AUDIT_INTERVAL

        # Regenerated each time the device daemon starts; the backend uses it to tell "the same device reconnecting" from "another machine using the same name"
        self.instance_id = uuid.uuid4().hex
        self.audit = AuditLog(audit_log) if audit_log else None
        self._audit_started(
            network=network,
            allow_unsandboxed=allow_unsandboxed,
            sandbox=sandbox,
            grace=grace,
        )

    def _audit_started(
        self, *, network: list[str] | None, allow_unsandboxed: bool, sandbox: str | None, grace: float | None
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
            # On reconnect, report the input position received for each command, so the backend resends input from that position
            "commands": self.commands.positions(),
        }

    def pause(self, reason: str = "Operations are paused on the device; the computer can't be operated for now.") -> None:
        self.paused = reason
        self._audit("paused", reason=reason)

        for executor in self._executors.values():
            executor.pause(reason)

        self._close_browser_tunnels()
        self._report_state()

    def resume(self) -> None:
        self.paused = None
        self.emergency_stopped = False
        self._audit("resumed")

        for executor in self._executors.values():
            executor.resume()

        self._report_state()

    def emergency_stop(self, *, source: str = "owner") -> None:
        self.paused, self.emergency_stopped = "The device has been emergency-stopped; the computer can't be operated for now.", True
        self._audit("emergency_stop", source=source)

        for executor in self._executors.values():
            executor.emergency_stop()

        self._close_browser_tunnels()
        self._report_state()

    def _close_browser_tunnels(self) -> None:
        # When paused, drop established browser connections (new ones are refused by _allowed_port); the backend reconnects after resuming
        for queue in self._tunnels.values():
            queue.put_nowait(None)
        self._tunnels.clear()

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
        # This listens on the daemon's own display; right after the framework sends keyboard input to it, key presses may come from the framework itself
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
                logger.warning("Connection to the backend dropped: %s", error)
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
                logger.warning("Refused a connection with an invalid token")
                self._audit("connection_refused", peer=peer, reason="invalid token")
                await refuse_handshake(socket)
                return
            if active.locked():
                self._audit("connection_refused", peer=peer, reason="a backend is already connected")
                await refuse_handshake(socket, "409 Conflict")
                return

            async with active:
                await finish_handshake(socket, headers)
                try:
                    await self.serve(socket.send_text, socket.receive_text, socket.abort)
                except Exception as error:
                    logger.warning("Connection to the backend dropped: %s", error)
                finally:
                    await socket.close()

        server = await asyncio.start_server(handle, host, port, ssl=context)
        logger.info("Waiting for the backend to connect on %s:%s", host, port)
        self._audit("listening", address=f"{host}:{port}", tls=bool(tls_cert))

        async with server:
            await server.serve_forever()

    async def serve(self, send: Any, receive: Any, abort: Any = None) -> None:
        if self.policy is not None:
            # Clean up transfer files left behind by earlier interrupted transfers (only those untouched for a long time)
            await asyncio.to_thread(helper.clean_transfers, os.path.join(self.policy.data_dir, "tmp"))

        await send(json.dumps(self.register_message(), ensure_ascii=False))
        reply = json.loads(await receive())
        if reply.get("type") != "registered":
            self._audit("register_refused", reason=reply.get("reason"))
            if reply.get("retry"):
                raise ConnectionError(f"The backend isn't accepting connections right now: {reply.get('reason')}")
            raise PermissionError(f"The backend refused this device: {reply.get('reason')}")

        if self.grace_override is None and reply.get("grace"):
            self.grace = float(reply["grace"])

        logger.info("Connected to the backend as device %s", self.name)
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
                    raise ConnectionError(f"No message from the backend within {HEARTBEAT_TIMEOUT} seconds") from None
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
            # On a half-dead connection, writes hang in drain() until the TCP timeout (over ten minutes), and commands hang along with them
            logger.warning("Sending a message to the backend didn't finish within %s seconds; disconnecting and reconnecting", SEND_TIMEOUT)
            if self._send is send:
                self._send = None
                if abort is not None:
                    abort()
            return False
        except Exception:
            return False

        return True

    def _dispatch(self, message: dict[str, Any]) -> None:
        # An invalid control message raises right away; the send/receive loop drops the connection without changing any state
        if message.get("type") == "call":
            self._spawn(self._handle_call(message))
            return

        try:
            parsed = protocol.parse_inbound(message)
        except protocol.ValidationError as error:
            problem = error.errors()[0].get("msg") if error.errors() else str(error)
            raise ValueError(f"Invalid fields in message {message.get('type')!r}: {problem}") from None

        if parsed is None:
            return  # Unknown types (e.g. pong) are ignored, for protocol backward compatibility

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
            # Register immediately: connecting to the browser takes time, and data arriving meanwhile must not be lost
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

        # Large results (screenshots, file reads) are sent in chunks; the last result states the total number of chunks
        text = json.dumps(value, ensure_ascii=False)
        parts = [text[start : start + RESULT_PART_SIZE] for start in range(0, len(text), RESULT_PART_SIZE)]
        for part in parts[:-1]:
            await self._post({"type": "result_part", "id": call_id, "data": part})

        await self._post({"type": "result", "id": call_id, "json": parts[-1] if parts else "null"})

    def _workspace(self) -> DevicePolicy:
        if self.policy is None:
            raise PermissionError("This device doesn't expose a workspace")
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
            # The live view has several frames per second: one viewing session is logged once per minute in the audit log
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
        # Check permissions before checking existence, so the backend can't use this to probe whether arbitrary paths exist on the device
        path = self._readable(call.path)
        if not os.path.exists(path):
            return None
        # Each entry in the directory (including where symlinks point) is also checked against the exposed directories
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
            raise PermissionError("The device doesn't expose its screen")
        return await self._executor(self._display(call.display)).handle(call.computer_op, call.arguments_)

    def _display(self, requested: str | None) -> str | None:
        if requested is None:
            return self.displays[0]
        if requested not in self.displays:
            if self.displays == [None]:
                raise PermissionError(f"This device has only one display; display {requested} can't be specified")
            raise PermissionError(f"This device doesn't expose display {requested}; exposed displays are {', '.join(map(str, self.displays))}")
        return requested

    async def _browser_start(self, call: protocol.BrowserStart) -> int:
        if not self.browser_enabled:
            raise PermissionError("The device doesn't expose a browser")
        if self.paused:
            raise PermissionError(self.paused)

        options = BrowserOptions.model_validate(call.options)
        if options.executable:
            raise PermissionError("The browser on the device is located by the device daemon itself; specifying an executable isn't allowed")

        browser_process.check_safe_args(options.args)

        # A headed browser appears on the first display the device owner exposed; the backend doesn't choose it
        options = options.model_copy(update={"display": None if options.headless else self.displays[0]})
        return await browser_process.start_browser(options)

    async def _browser_stop(self, call: protocol.BrowserStop) -> None:
        if not self.browser_enabled:
            raise PermissionError("The device doesn't expose a browser")
        await browser_process.stop_browser(call.profile)

    # Browser debugging connections: can only connect to browsers on this device started by the framework
    async def _allowed_port(self, port: int) -> bool:
        return self.browser_enabled and not self.paused and port in await browser_process.framework_ports()

    async def _tunnel(self, stream_id: str, port: int, incoming: asyncio.Queue[bytes | None]) -> None:
        allowed = await self._allowed_port(port)
        self._audit("browser_connect", port=port, outcome="ok" if allowed else "denied")

        if not allowed:
            self._tunnels.pop(stream_id, None)
            await self._post({"type": "tcp_close", "id": stream_id, "reason": "The device doesn't allow connecting to this port"})
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
    network: list[str] | None,
    allow_unsandboxed: bool,
    screen: bool,
    browser: bool,
) -> None:
    if protect not in PROTECT_TEMPLATES:
        raise ValueError(f"Invalid --protect value {protect!r}; valid values are {' or '.join(PROTECT_TEMPLATES)}")

    if sandbox is not None:
        if not workspace:
            raise ValueError("--sandbox is only for running commands in exposed directories; also use --workspace to specify the exposed directories")
        if sandbox not in ("srt", "none"):
            raise ValueError(f"Invalid --sandbox value {sandbox!r}; valid values are srt or none")

    if allow_unsandboxed and sandbox is None:
        raise ValueError("--allow-unsandboxed must be used together with --sandbox; commands can't run without --sandbox")
    if not (workspace or screen or browser):
        raise ValueError("Nothing is exposed; specify at least one of --workspace, --screen or --browser")
    if screen and importlib.util.find_spec("PIL") is None:
        # Screenshots are scaled and cropped on the device before being sent back
        raise ValueError("Exposing the screen requires Pillow; run pip install Pillow pyautogui")


def opened_displays(displays: list[str] | None) -> list[str | None]:
    if not sys.platform.startswith("linux"):
        if displays:
            raise ValueError("--display only applies to Linux")
        return [None]

    unique: list[str | None] = list(dict.fromkeys(display.strip() for display in displays or [] if display.strip()))
    return unique or [default_display()]
