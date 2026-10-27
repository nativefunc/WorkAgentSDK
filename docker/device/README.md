# Device program image

Use a container as a remote device: once the container starts it runs the device program, and after the backend connects, the agent's commands and file operations run inside the container.

## Build

Run from the source root:

```bash
docker build -f docker/device/Dockerfile -t work-agent-device .
```

To use a browser inside the container, add `BROWSER=1`:

```bash
docker build -f docker/device/Dockerfile --build-arg BROWSER=1 -t work-agent-device:browser .
```

## Run

Backend connects to the container:

```bash
docker run -d -e DEVICE_NAME=box -e DEVICE_TOKEN=... -p 7000:7000 work-agent-device
```

Container connects to the backend:

```bash
docker run -d -e DEVICE_NAME=box -e DEVICE_TOKEN=... \
    -e DEVICE_URL=wss://myapp.com/work_agent_sdk/nodes work-agent-device
```

Other device program arguments go after the image name, for example to expose the browser:

```bash
docker run -d -e DEVICE_NAME=box -e DEVICE_TOKEN=... -p 7000:7000 work-agent-device:browser --browser
```

For the backend side, see [Nodes](../../docs/reference/nodes.md).

## Environment variables

| Name | Default | Description |
| :-- | :-- | :-- |
| `DEVICE_NAME` | Required | Device name; same as the name of the backend `Device` |
| `DEVICE_TOKEN` | Required | Token |
| `DEVICE_URL` | None | Backend address. When set, the container connects to the backend |
| `DEVICE_LISTEN` | `0.0.0.0:7000` | Address to wait for the backend on when `DEVICE_URL` is not set |
| `DEVICE_WORKSPACE` | `/workspace` | Directory exposed to the backend |
| `DEVICE_SANDBOX` | `srt` | Values: `srt` or `none`. With `srt`, commands run in a sandbox, can only write to the workspace, and can only reach domains the backend allows |
| `DEVICE_NETWORK` | None | Upper bound on the domains the sandbox may reach, comma-separated, e.g. `pypi.org,github.com`. The backend can only allow domains within this bound; no bound when unset |
| `DEVICE_AUDIT_LOG` | `/var/log/work-agent/audit.jsonl` | Audit log file recording the backend's operations in the container. Set to empty to disable |

## Audit log

The audit log is stored in the container and is deleted along with it. Mount a directory to keep it:

```bash
docker run -d -e DEVICE_NAME=box -e DEVICE_TOKEN=... -p 7000:7000 \
    -v /var/log/agents/box:/var/log/work-agent work-agent-device
```

## Sandbox

Inside a container, srt uses a weaker sandbox mode suited to Docker, which isolates less than running the device program directly on a machine.
