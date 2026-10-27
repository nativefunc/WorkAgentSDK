# Nodes

```python
from work_agent_sdk import Device, Local, SharedFolder
```

## Local

```python
Local(*, env: dict[str, str] | None = None, esc_stop: bool = False)
```

The local node, named `"local"`. When `Runner` doesn't set `nodes`, only the local machine is available; once `nodes` is set, you must list `Local()` to use the local machine.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `env` | `dict[str, str] \| None` | `None` | Environment variables passed to commands. By default commands inherit only a few variables such as `PATH`, `HOME` and `LANG` |
| `esc_stop` | `bool` | `False` | Whether pressing Esc pauses computer operations. Requires `pynput` |

## Device

```python
Device(
    name: str,
    *,
    connect: str | None = None,
    token: str | None = None,
    wake: Callable | None = None,
    wait: float = 60,
    grace: float = 60,
)
```

A remote device node.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `name` | `str` | Required | Node name; must match the device program's `--name` |
| `connect` | `str \| None` | `None` | Device address, e.g. `ws://build-box.internal:7000`; supports `${ENV_VAR}`. When set, the backend connects to the device and the device program uses `--listen`; when unset, the device program connects to the backend with `--url`, and the backend handles the connection with [`runner.nodes.websocket()`](#nodes) |
| `token` | `str \| None` | `None` | Token. Required when `connect` is set; supports `${ENV_VAR}` |
| `wake` | `Callable \| None` | `None` | Function called when the device is offline, e.g. to wake it |
| `wait` | `float` | `60` | Maximum time to wait while the device is offline (seconds) |
| `grace` | `float` | `60` | Time to wait for the device to reconnect after a disconnect (seconds); commands on the device keep running meanwhile |

## SharedFolder

```python
SharedFolder(name: str, mounts: dict[str, str])
```

The same directory mounted on several machines (e.g. NFS), listed in `Runner`'s `shared_folders` parameter. The device program on a remote device must expose this directory with `--workspace`.

| Parameter | Type | Description |
| :-- | :-- | :-- |
| `name` | `str` | Name. Letters, digits, `_` and `-` only, up to 64 characters |
| `mounts` | `dict[str, str]` | Node name to the path of this directory on that node. Paths may start with `~` |

## Nodes

Methods of `runner.nodes`.

| Method | Description |
| :-- | :-- |
| `add(node, name=None)` | Register a node; `name` defaults to the node's name. Must be registered again after the backend restarts |
| `remove(name)` | Remove a node |
| `names()` | Return node names |
| `is_online(name)` | Return whether a node is online |
| `status()` | Return a dict from node name to [device status](#device-status) |
| `issue_token(name)` | Issue a token for a device; the old token stops working. Tokens are stored in the Runner's data directory |
| `revoke(name)` | Revoke a device's token |
| `websocket(websocket)` | Handle a device's WebSocket connection, used when the device connects to the backend |
| `connect(send, receive)` | Handle a device's connection, for frameworks that don't support `websocket()` |
| `files(name)` | Return the files on a node; see [ScopedFiles](workspace.md#scopedfiles). Paths must be absolute or start with `~` |
| `add_shared_folder(folder)` | Register a `SharedFolder` |

### Device status

When the device is offline only `online` is present.

| Field | Type | Description |
| :-- | :-- | :-- |
| `online` | `bool` | Whether it is online |
| `os` | `str` | Operating system |
| `shell` | `str` | Shell |
| `home` | `str` | User home directory |
| `workspace` | `dict \| None` | Exposed directories and sandbox settings. `roots` are the exposed directories |
| `screen` | `bool` | Whether the screen is exposed |
| `browser` | `bool` | Whether launching a browser is allowed |
| `paused` | `bool` | Whether it is paused. The device owner pauses by pressing Esc; while paused, computer and browser operations return an error |
| `last_seen` | `float` | Time the last message was received from the device |

## Node events

Node events returned by `runner.events()`.

```python
from work_agent_sdk.events import NodeConnected, NodeDisconnected, NodeRefused
```

| Event | Description |
| :-- | :-- |
| `NodeConnected` | Device came online. `node` is the node name |
| `NodeDisconnected` | Device went offline |
| `NodeRefused` | Device connection was refused. `detail` is the reason |

## Device program arguments

```bash
python -m work_agent_sdk.cli device --name <device-name> [options]
```

The device program's arguments determine what the backend may do on the device; backend settings cannot go beyond them.

| Argument | Description |
| :-- | :-- |
| `--name` | Device name; must match the node name registered on the backend |
| `--url` | Backend address, e.g. `wss://myapp.com/work_agent_sdk/nodes`. Used when the device connects to the backend |
| `--listen` | Address to listen on, e.g. `0.0.0.0:7000`. Used when the backend connects to the device |
| `--tls-cert`, `--tls-key` | Certificate and private key. When set, the backend connects with a `wss://` address |
| `--token`, `--token-file` | Token or token file. The `WORK_AGENT_DEVICE_TOKEN` environment variable also works |
| `--workspace` | Directory to expose; may be given multiple times |
| `--sandbox` | Sandbox used to run commands. Values: `srt` or `none`. Commands cannot run when unset |
| `--network` | Allowed domains, comma-separated. Commands can reach the intersection of the backend's `SRT(network=...)` and this list. Uses the backend's setting when unset |
| `--allow-unsandboxed` | Allow the backend to run commands outside the sandbox |
| `--protect` | Protection rules. Values: `standard` or `none`. `standard` blocks writes to shell startup files, git hooks and similar files, and blocks reads of credential directories |
| `--env` | Name of an environment variable passed to commands; may be given multiple times |
| `--screen` | Expose the screen |
| `--screen-deny` | Apps that may not be operated; supports the `*` wildcard |
| `--screen-max-tier` | Highest access tier allowed. Values: `view`, `click` or `full` |
| `--display` | Linux X display number to expose, e.g. `:1`; may be given multiple times |
| `--browser` | Allow the backend to launch a browser |
| `--headless` | The screen is unattended, e.g. a container or cloud desktop |
| `--disconnect-grace` | Maximum time commands are kept after a disconnect (seconds) |
| `--srt-binary`, `--srt-nested`, `--srt-settings` | srt executable path, whether to use the weaker sandbox mode suited to Docker, and an extra settings file |
| `--audit-log` | Log file recording backend operations, in JSON Lines format |

## Examples

- [nodes/device_listen.py](../../examples/nodes/device_listen.py): backend connects to the device
- [apps/device_connect](../../examples/apps/device_connect): device connects to the backend; issuing device tokens
- [advanced/shared_folder](../../examples/advanced/shared_folder): workspace, browser and computer on three machines, exchanging files through a shared folder
- [docker/device](../../docker/device): use a container as a remote device
