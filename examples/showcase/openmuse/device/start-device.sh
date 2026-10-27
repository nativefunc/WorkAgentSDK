#!/usr/bin/env bash
# Start the OpenMuse device program.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
CONFIG_DIR="$HOME/.openmuse"
CONFIG="$CONFIG_DIR/device.json"

usage() {
    cat <<EOF
Usage:
  $0 --server http://127.0.0.1:8000 --code 123456

Environment variables:
  PYTHON                    Python used to run the node, default python3
  OPENMUSE_WORKSPACE        Workspace directory, default ~/OpenMuse/workspace
  OPENMUSE_NETWORK          Domains the sandbox may reach, default pypi.org,files.pythonhosted.org
  OPENMUSE_SCREEN=0         Don't expose the screen
  OPENMUSE_BROWSER=0        Don't expose the browser
  OPENMUSE_SCREEN_MAX_TIER  Highest screen access tier: view, click, full (default)
  OPENMUSE_HEADLESS=1       Unattended (server, container); don't listen for Esc
  OPENMUSE_SRT_NESTED=1     Use when running inside a container
EOF
}

server_arg=""
code_arg=""
while [ $# -gt 0 ]; do
    case "$1" in
        --server) server_arg="${2:-}"; shift 2 ;;
        --code) code_arg="${2:-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown argument: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

# Exchange the pairing code for a device token and write it to ~/.openmuse/device.json (mode 600)
if [ -n "$code_arg" ]; then
    [ -n "$server_arg" ] || { echo "Please also specify --server (the address shown in the app)" >&2; exit 2; }
    mkdir -p "$CONFIG_DIR"
    chmod 700 "$CONFIG_DIR"
    "$PYTHON" - "$server_arg" "$code_arg" "$CONFIG" <<'PY'
import hashlib, json, os, sys, urllib.error, urllib.request

server, code, path = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
request = urllib.request.Request(
    server + "/api/device/claim",
    data=json.dumps({"code": code}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.load(response)
except urllib.error.HTTPError as error:
    try:
        detail = json.load(error).get("detail")
    except Exception:
        detail = None
    sys.exit(f"Pairing failed: {detail or error}")
except OSError as error:
    sys.exit(f"Cannot reach {server}: {error}")

data["code_hash"] = hashlib.sha256(code.encode()).hexdigest()
descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(descriptor, "w") as file:
    json.dump(data, file)
print(f"Paired: this computer is {data['name']}; credentials saved to {path}")
PY
fi

if [ -z "${WORK_AGENT_DEVICE_TOKEN:-}" ] && [ -f "$CONFIG" ]; then
    saved="$("$PYTHON" - "$CONFIG" <<'PY'
import json, shlex, sys

data = json.load(open(sys.argv[1]))
for name, value in (
    ("saved_server", data["url"]),
    ("saved_device", data["name"]),
    ("saved_token", data["token"]),
    ("saved_workspace", data.get("workspace") or ""),
):
    print(f"{name}={shlex.quote(value)}")
PY
)"
    saved_server="" saved_device="" saved_token="" saved_workspace=""
    eval "$saved"
    OPENMUSE_SERVER="${OPENMUSE_SERVER:-$saved_server}"
    OPENMUSE_DEVICE="${OPENMUSE_DEVICE:-$saved_device}"
    WORK_AGENT_DEVICE_TOKEN="$saved_token"
    OPENMUSE_WORKSPACE="${OPENMUSE_WORKSPACE:-$saved_workspace}"
fi

if [ -z "${WORK_AGENT_DEVICE_TOKEN:-}" ] || [ -z "${OPENMUSE_SERVER:-}" ] || [ -z "${OPENMUSE_DEVICE:-}" ]; then
    echo "This computer isn't paired yet. In the app, go to Profile → Computer, tap Connect a computer, and pair with the command shown, for example:" >&2
    echo "  $0 --server https://muse.example.com --code 482913" >&2
    exit 1
fi
export WORK_AGENT_DEVICE_TOKEN

WORKSPACE="${OPENMUSE_WORKSPACE:-$HOME/OpenMuse/workspace}"
WORKSPACE="${WORKSPACE/#\~/$HOME}"
NETWORK="${OPENMUSE_NETWORK:-pypi.org,files.pythonhosted.org}"
SYSTEM="$(uname -s)"

install_hint() {
    if command -v apt-get >/dev/null; then echo "sudo apt install $*"
    elif command -v dnf >/dev/null; then echo "sudo dnf install $*; ripgrep is in the EPEL repository, or download it from https://github.com/BurntSushi/ripgrep/releases"
    elif command -v yum >/dev/null; then echo "sudo yum install $*"
    elif command -v brew >/dev/null; then echo "brew install $*"
    else echo "Install $* with your system's package manager"
    fi
}

warn() { printf '\033[33m%s\033[0m\n' "$*" >&2; }
fail() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

if ! "$PYTHON" -c "import work_agent_sdk" 2>/dev/null; then
    version="$("$PYTHON" --version 2>&1 || echo "not found")"
    fail "work_agent_sdk not found in $PYTHON ($version). Use PYTHON=/path/to/python to point to a Python (3.11+) with the SDK installed, such as the python in a venv; or run $PYTHON -m pip install . from the repository root"
fi
command -v srt >/dev/null || fail "srt not found: install Node.js 22.12 or later, then run npm install -g @anthropic-ai/sandbox-runtime"
if [ "$SYSTEM" = "Linux" ]; then
    for tool in bwrap socat rg; do
        command -v "$tool" >/dev/null || fail "$tool not found: please install bubblewrap, socat and ripgrep ($(install_hint bubblewrap socat ripgrep))"
    done
fi

# The audit log lives outside the workspace, so commands inside the sandbox can't read or write it
mkdir -p "$WORKSPACE"
chmod 700 "$(dirname "$WORKSPACE")" "$WORKSPACE"
AUDIT_LOG="$(dirname "$WORKSPACE")/audit.jsonl"

args=(
    device
    --name "$OPENMUSE_DEVICE"
    --url "$OPENMUSE_SERVER"
    --workspace "$WORKSPACE"
    --sandbox srt
    --protect standard
    --network "$NETWORK"
    --srt-settings "$HERE/srt-settings.json"
    --audit-log "$AUDIT_LOG"
    --disconnect-grace 120
)
[ "${OPENMUSE_SRT_NESTED:-0}" = 1 ] && args+=(--srt-nested)

if [ "${OPENMUSE_SCREEN:-1}" != 0 ]; then
    screen_ok=1
    if [ "$SYSTEM" = "Linux" ]; then
        if [ "${XDG_SESSION_TYPE:-x11}" = "wayland" ]; then
            warn "This is a Wayland session, which doesn't support screen control; choose an X11 (Xorg) session on the login screen. The screen won't be exposed this time."
            screen_ok=0
        fi
        for tool in xdotool xprop xwininfo; do
            command -v "$tool" >/dev/null || { warn "$tool not found ($(install_hint xdotool x11-utils); on dnf systems x11-utils is called xorg-x11-utils). The screen won't be exposed this time."; screen_ok=0; }
        done
    else
        "$PYTHON" -c "import pyautogui" 2>/dev/null \
            || { warn "pyautogui not found ($PYTHON -m pip install pyautogui Pillow). The screen won't be exposed this time."; screen_ok=0; }
    fi
    "$PYTHON" -c "import PIL" 2>/dev/null || { warn "Pillow not found ($PYTHON -m pip install Pillow). The screen won't be exposed this time."; screen_ok=0; }

    if [ "$screen_ok" = 1 ]; then
        args+=(--screen --screen-max-tier "${OPENMUSE_SCREEN_MAX_TIER:-full}")
        # Apps that may not be operated; also applies during user takeover
        for app in "*1Password*" "*Bitwarden*" "*KeePass*" "*Keychain*" "*Wallet*" "*Authenticator*" \
                   "System Settings" "System Preferences" "*gnome-control-center*" "*Terminal*" "*iTerm*" \
                   "*Konsole*" "*xterm*" "*Alacritty*" "*WezTerm*" "*kitty*"; do
            args+=(--screen-deny "$app")
        done
        [ "${OPENMUSE_HEADLESS:-0}" = 1 ] && args+=(--headless)
        [ "$SYSTEM" = "Darwin" ] && warn "On first use, grant the terminal \"Accessibility\" and \"Screen Recording\" in \"System Settings → Privacy & Security\"."
    fi
fi

if [ "${OPENMUSE_BROWSER:-1}" != 0 ]; then
    args+=(--browser)
fi

echo "OpenMuse device $OPENMUSE_DEVICE → $OPENMUSE_SERVER"
echo "Workspace: $WORKSPACE"
echo "Audit log: $AUDIT_LOG"
[ "${OPENMUSE_SCREEN:-1}" != 0 ] && [ "${OPENMUSE_HEADLESS:-0}" != 1 ] && echo "While the agent is operating the screen, press Esc at any time to pause."
exec "$PYTHON" -m work_agent_sdk.cli "${args[@]}"
