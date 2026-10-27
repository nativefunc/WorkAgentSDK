from __future__ import annotations

import contextlib
import os
import shlex
import shutil
import sys
import uuid
from collections.abc import AsyncIterator, Callable

from pydantic import BaseModel, Field

from work_agent_sdk.host.commands.env import check_command_env
from work_agent_sdk.host.commands.process import OutputChunk, Stdin, run_process
from work_agent_sdk.host.commands.sandbox import NoSandbox, Sandbox, Scope, wrap
from work_agent_sdk.host.files.paths import NodePaths, local_style, local_system


class Command(BaseModel):
    line: str
    workspace: str
    cwd: str
    tmp: str
    sandbox: Sandbox
    readable: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    timeout: float | None = None
    # Request to run outside the sandbox (already approved). Whether a device allows it is up to the device owner
    unsandboxed: bool = False


def local_shell() -> str:
    if sys.platform == "win32":
        return "powershell"
    return "bash" if shutil.which("bash") else "sh"


def local_scope(command: Command) -> Scope:
    home = os.path.expanduser("~")
    return Scope(
        workspace=command.workspace,
        cwd=command.cwd,
        tmp=command.tmp,
        data_dir=NodePaths(home, local_style()).data_dir,
        home=home,
        shell=local_shell(),
        os=local_system(),
        readable=list(command.readable),
    )


# File operations in the workspace sandbox run helper.py as a command; its location is given by the executor and can't be overridden by the command
HELPER_VARIABLES = {
    "WORK_AGENT_PYTHON": sys.executable,
    "WORK_AGENT_FILE_HELPER": os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "files", "helper.py"
    ),
}

# Device owner restrictions: (sandbox requested by the backend, scope, whether running outside the sandbox is requested) -> (sandbox actually used, scope)
Restrict = Callable[[Sandbox, Scope, bool], tuple[Sandbox, Scope]]


async def run_command(
    command: Command,
    stdin: Stdin = None,
    *,
    variables: dict[str, str],
    restrict: Restrict | None = None,
    on_start: Callable[[int], None] | None = None,
) -> AsyncIterator[OutputChunk]:
    scope = local_scope(command)
    sandbox = command.sandbox
    env_path: str | None = None
    try:
        check_command_env(command.env)

        if restrict is not None:
            sandbox, scope = restrict(sandbox, scope, command.unsandboxed)

        os.makedirs(scope.tmp, exist_ok=True)

        if not os.path.isdir(scope.cwd):
            raise FileNotFoundError(f"Working directory does not exist: {scope.cwd}")

        line, env_path = _apply_command_env(command.line, command.env, sandbox, scope)
        argv = await wrap(sandbox, line, scope)
    except (PermissionError, FileNotFoundError, ValueError, NotImplementedError) as error:
        _remove_env_file(env_path)
        yield OutputChunk("stderr", f"Cannot run: {error}\n".encode())
        yield OutputChunk("exit", code=126)
        return

    # The sandbox program is looked up in the executing node's own PATH, unaffected by the command's environment variables
    launcher = shutil.which(argv[0], path=variables.get("PATH")) or argv[0]
    argv = [launcher, *argv[1:]]

    # srt runs outside the sandbox: if the backend's environment variables got into its launching process, PATH and LD_PRELOAD could swap out the programs it calls
    process_env = {**variables, **HELPER_VARIABLES}
    if isinstance(sandbox, NoSandbox):
        process_env.update(command.env)

    try:
        async for chunk in run_process(
            argv, cwd=scope.cwd, env=process_env, stdin=stdin, timeout=command.timeout, on_start=on_start
        ):
            yield chunk
    except FileNotFoundError:
        # Only happens at startup: the sandbox program or shell isn't installed
        yield OutputChunk("stderr", f"Cannot run: {argv[0]} was not found on the executing node\n".encode())
        yield OutputChunk("exit", code=127)
    finally:
        _remove_env_file(env_path)


def _apply_command_env(line: str, env: dict[str, str], sandbox: Sandbox, scope: Scope) -> tuple[str, str | None]:
    if not env or isinstance(sandbox, NoSandbox):
        return line, None

    path = os.path.join(scope.tmp, f".work-agent-env-{uuid.uuid4().hex}")
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
        for name, value in env.items():
            file.write(f"export {name}={shlex.quote(value)}\n")

    return f". {shlex.quote(path)}; {line}", path


def _remove_env_file(path: str | None) -> None:
    if path is not None:
        with contextlib.suppress(OSError):
            os.remove(path)
