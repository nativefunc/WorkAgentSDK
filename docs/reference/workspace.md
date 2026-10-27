# Workspace

```python
from work_agent_sdk import SRT, NoSandbox, Shell, ViewImage, Workspace
```

## Workspace

```python
Workspace(path: str, *, sandbox: SRT | NoSandbox, node: str = "local", description: str = "")
```

The directory a session uses, passed as the `workspace` argument of `runner.new_session()`. A session and its child sessions share one workspace.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `path` | `str` | Required | Workspace directory. Created automatically if missing |
| `sandbox` | `SRT \| NoSandbox` | Required | Sandbox |
| `node` | `str` | `"local"` | Node the workspace is on. See [Nodes](nodes.md) |
| `description` | `str` | `""` | Description of the workspace, sent to the model |

## SRT

```python
SRT(*, network: list[str] = [], write: list[str] = [], protect: list[str] = [], deny_read: list[str] = ..., read: list[str] = [], binary: str = "srt", nested: bool = False, settings: dict = {})
```

Runs commands with Sandbox Runtime (srt). By default commands can only write to the workspace and temporary directories and have no network access. Relative paths are relative to the workspace; `~` is the user's home directory on the machine the workspace is on.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `network` | `list[str]` | `[]` | Domains that may be accessed |
| `write` | `list[str]` | `[]` | Paths outside the workspace that may be written |
| `protect` | `list[str]` | `[]` | Paths in the workspace that may not be written, e.g. `.env` |
| `deny_read` | `list[str]` | Credential directories such as `~/.ssh` and `~/.aws` | Paths that may not be read. Replaces the default when set |
| `read` | `list[str]` | `[]` | Paths inside `deny_read` that may still be read |
| `binary` | `str` | `"srt"` | Path to the srt executable |
| `nested` | `bool` | `False` | Whether to use the weaker sandbox mode suited to Docker |
| `settings` | `dict` | `{}` | Other settings merged into the srt configuration |

## NoSandbox

```python
NoSandbox()
```

No sandbox; commands run directly. For isolated environments such as containers and virtual machines.

## Shell

```python
Shell(*, timeout: float = 30, max_timeout: float = 600, max_output: int = 30000, max_output_mb: float = 10, max_processes: int = 50, allow_unsandboxed: bool = False)
```

Toolset that lets the agent run commands in the workspace.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `timeout` | `float` | `30` | How long to wait for a command to finish (seconds). After the timeout the command keeps running in the background, and the model can check its output later |
| `max_timeout` | `float` | `600` | Longest wait the model may request (seconds) |
| `max_output` | `int` | `30000` | Maximum number of output characters returned to the model each time |
| `max_output_mb` | `float` | `10` | Limit on the output kept per process (MB) |
| `max_processes` | `int` | `50` | Maximum number of processes running at once in a session |
| `allow_unsandboxed` | `bool` | `False` | Whether the model may request to run commands outside the sandbox. The SDK doesn't approve such requests; use a `before_tool` hook to ask the user to confirm |

| Tool | Description |
| :-- | :-- |
| `shell` | Run a command. The `unsandboxed` and `unsandboxed_reason` arguments request running outside the sandbox |
| `shell_input` | Check the output of a background command, send input to it, or terminate it |

## ViewImage

```python
ViewImage(*, local: bool = False)
```

Tool that lets the model view images; supports png, jpg, gif and webp. The model must support image input; see `input_types`.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `local` | `bool` | `False` | Whether to read files on the local machine. When `True`, paths must be absolute |

## BoundWorkspace

The workspace returned by `session.workspace()` and `ctx.workspace`.

### Attributes

| Name | Type | Description |
| :-- | :-- | :-- |
| `path` | `str` | Absolute path of the workspace directory |
| `files` | `ScopedFiles` | Files in the workspace. See [ScopedFiles](#scopedfiles) |
| `sandbox` | `SRT \| NoSandbox` | Current sandbox |
| `description` | `str` | Description of the workspace |

### Methods

| Method | Description |
| :-- | :-- |
| [`run(command, ...)`](#run) | Run a command and wait for it to finish |
| [`start_process(command, ...)`](#start_process) | Start a process and return immediately |
| `processes(children=False)` | Return the processes started by the session. Includes child sessions' processes when `children=True` |
| `process(process_id)` | Return a process |
| `get_sandbox()` | Return a copy of the sandbox |
| `set_sandbox(sandbox)` | Set the sandbox; takes effect from the next command and also applies to child sessions |

### run()

```python
async def run(
    command: str,
    *,
    cwd: str | None = None,
    stdin: bytes | AsyncIterable[bytes] | None = None,
    timeout: float | None = 120,
    unsandboxed: bool = False,
) -> RunResult
```

Runs a command, waits for it to finish, and returns a [`RunResult`](#runresult). The command does not go through hooks.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `command` | `str` | Required | Command |
| `cwd` | `str \| None` | `None` | Directory to run the command in; must be inside the workspace. The workspace directory when unset |
| `stdin` | `bytes \| AsyncIterable[bytes] \| None` | `None` | Standard input |
| `timeout` | `float \| None` | `120` | Timeout (seconds) |
| `unsandboxed` | `bool` | `False` | Whether to run outside the sandbox |

### start_process()

```python
async def start_process(
    command: str,
    *,
    cwd: str | None = None,
    key: str | None = None,
    unsandboxed: bool = False,
    max_output_mb: float = 10,
) -> Process
```

Starts a process and immediately returns a [`Process`](#process). The process is terminated when the session closes.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `command` | `str` | Required | Command |
| `cwd` | `str \| None` | `None` | Directory to run the command in; must be inside the workspace. The workspace directory when unset |
| `key` | `str \| None` | `None` | Process key. If the session already has a process with the same key, that process is returned |
| `unsandboxed` | `bool` | `False` | Whether to run outside the sandbox |
| `max_output_mb` | `float` | `10` | Limit on the output kept (MB) |

## RunResult

| Field | Type | Description |
| :-- | :-- | :-- |
| `exit_code` | `int` | Exit code |
| `stdout` | `str` | Standard output |
| `stderr` | `str` | Standard error |
| `ok` | `bool` | Whether the exit code is 0 |

## Process

| Attribute | Type | Description |
| :-- | :-- | :-- |
| `id` | `str` | Process ID |
| `command` | `str` | Command |
| `status` | `str` | Status. Values: `running`, `exited` or `killed` |
| `exit_code` | `int \| None` | Exit code. `None` while running |
| `started_at` | `float` | Start time |
| `ended_at` | `float \| None` | End time |

| Method | Description |
| :-- | :-- |
| `output(after=0, follow=True)` | Yield output in chunks starting at byte `after`; each chunk has `text` and `offset`. With `follow=True`, keeps yielding until the process ends |
| `text(after=0)` | Return the output available so far, starting at byte `after` |
| `write(text)` | Send text to the process's input |
| `wait()` | Wait for the process to end; returns the exit code |
| `kill()` | Terminate the process |
| `refresh()` | Refresh the attributes |

## ScopedFiles

Methods of `workspace.files`. Relative paths are relative to the workspace; file operations are subject to the sandbox.

| Method | Description |
| :-- | :-- |
| `read_file(path, max_size=None)` | Return the file contents (`bytes`). `max_size` defaults to 100 MB |
| `read(path, max_size=None)` | Yield the file contents in chunks |
| `write(path, data)` | Write a file and return its [`FileInfo`](#fileinfo). Missing directories are created automatically |
| `list(path=".")` | Return the files in a directory, each a `FileInfo` |
| `stat(path=".")` | Return a `FileInfo` |
| `exists(path)` | Return whether the file exists |
| `make_dir(path)` | Create a directory |
| `delete_file(path)` | Delete a file |
| `delete_dir(path, recursive=False)` | Delete a directory. With `recursive=True`, also deletes its contents |
| `copy(source, target)` | Copy a file |
| `move(source, target)` | Move a file |

## FileInfo

| Field | Type | Description |
| :-- | :-- | :-- |
| `path` | `str` | Path |
| `name` | `str` | File name |
| `is_dir` | `bool` | Whether it is a directory |
| `size` | `int` | Size (bytes) |
| `modified` | `float` | Modification time |
| `mime` | `str \| None` | MIME type |

## Examples

- [workspace/workspace.py](../../examples/workspace/workspace.py): the agent writes and runs code in the workspace; the app reads and writes files, runs commands and starts background processes
- [workspace/sandbox.py](../../examples/workspace/sandbox.py): configure the sandbox, allow domains within a session, ask the user to confirm before running commands outside the sandbox
