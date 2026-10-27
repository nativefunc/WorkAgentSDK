# OpenMuse

A personal AI assistant built on Work Agent SDK.

## Directory layout

```
openmuse/
├── server/               Backend, runs the agent
├── app/                  Mobile app
└── device/               Node startup script and Docker image
```

## Backend

Run from the source root:

```bash
pip install . -r examples/showcase/openmuse/server/requirements.txt
cp examples/showcase/openmuse/server/.env.example examples/showcase/openmuse/server/.env
```

Set `DASHSCOPE_API_KEY` in `examples/showcase/openmuse/server/.env`, then start:

```bash
cd examples/showcase/openmuse/server
uvicorn main:app --host 0.0.0.0 --port 8000
```

## App

Run from the `examples/showcase/openmuse/app` directory:

```bash
flutter pub get
flutter run --dart-define=OPENMUSE_SERVER=http://<backend-address>:8000
```

## Nodes

A node is a machine the agent works on, providing these resources:

- **Workspace**: read and write files, run shell commands
- **Browser**: visit web pages
- **Computer**: operate desktop apps

A node can run directly or in a Docker container; pick either.

### Run directly

Supports Linux and macOS. Install the following dependencies; run the `pip` command from the source root:

| Dependency | Linux | macOS |
| :-- | :-- | :-- |
| Python 3.11+ | `pip install . Pillow` | `pip install . Pillow pyautogui` |
| Node.js 22.12+ | `npm install -g @anthropic-ai/sandbox-runtime` | `npm install -g @anthropic-ai/sandbox-runtime` |
| System packages | bubblewrap, socat, ripgrep, xdotool, x11-utils | None |
| Browser | Chrome or Chromium | Chrome |

To use the computer resource, Linux needs an X11 session; on macOS, grant the terminal the "Accessibility" and "Screen Recording" permissions in "System Settings → Privacy & Security".

Get a pairing code from Profile → Computer in the app, then run from the source root:

```bash
./examples/showcase/openmuse/device/start-device.sh --server http://<backend-address>:8000 --code <pairing-code>
```

See `start-device.sh --help` for the available environment variables.

### Run in Docker

The container includes a virtual desktop, a browser and the shell sandbox, so none of the dependencies above are needed.

Get a pairing code in the app, then run from the source root:

```bash
docker build -f examples/showcase/openmuse/device/Dockerfile -t openmuse-desktop .
docker run -d -v openmuse-home:/home/muse \
    --security-opt seccomp=examples/showcase/openmuse/device/seccomp.json \
    --security-opt no-new-privileges --shm-size=1g \
    -e DEVICE_SERVER=http://<backend-address>:8000 -e DEVICE_CODE=<pairing-code> openmuse-desktop
```

Pairing credentials are stored in the volume. Give each user's cloud desktop its own volume (e.g. `-v openmuse-home-alice:/home/muse`); otherwise they share the same computer's credentials, files and browser sign-ins. Starting with the same volume and a new pairing code pairs it again.

`seccomp.json` lets Chromium and the shell sandbox inside the container create namespaces, which Docker's default seccomp profile does not allow.

## Security

Deploying the backend and nodes on different machines is recommended, to limit the impact of security issues.