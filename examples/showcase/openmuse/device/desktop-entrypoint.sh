#!/usr/bin/env bash
# Cloud desktop container entrypoint: start the Xvfb desktop, then run start-device.sh
set -euo pipefail

# On first start, pair with DEVICE_SERVER + DEVICE_CODE; credentials live in ~/.openmuse, so with a mounted volume no re-pairing is needed after restarts
if [ -z "${DEVICE_CODE:-}" ] && [ ! -f "$HOME/.openmuse/device.json" ] \
    && { [ -z "${DEVICE_NAME:-}" ] || [ -z "${DEVICE_TOKEN:-}" ] || [ -z "${DEVICE_URL:-}" ]; }; then
    echo "Please set DEVICE_SERVER and DEVICE_CODE (the address and pairing code shown under Profile → Computer in the app)" >&2
    exit 1
fi

export DISPLAY=:1
# Stale lock files survive a container restart; Xvfb won't start unless they are removed
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
Xvfb :1 -screen 0 "${SCREEN_SIZE:-1280x800x24}" -nolisten tcp &
for _ in $(seq 1 50); do
    xdpyinfo >/dev/null 2>&1 && break
    sleep 0.1
done

openbox &
# Window manager, desktop background, taskbar
desktop_conf="$HOME/.config/pcmanfm/default/desktop-items-0.conf"
if [ ! -f "$desktop_conf" ]; then
    mkdir -p "$(dirname "$desktop_conf")"
    printf '[*]\nwallpaper_mode=color\ndesktop_bg=#35577a\ndesktop_fg=#ffffff\ndesktop_shadow=#000000\nshow_trash=0\nshow_mounts=0\n' > "$desktop_conf"
fi
pcmanfm --desktop >/dev/null 2>&1 &
tint2 >/dev/null 2>&1 &

# Enable noVNC (port 6080) when VNC_PASSWORD is set
if [ -n "${VNC_PASSWORD:-}" ]; then
    mkdir -p "$HOME/.vnc"
    x11vnc -storepasswd "$VNC_PASSWORD" "$HOME/.vnc/passwd" >/dev/null
    x11vnc -display :1 -rfbauth "$HOME/.vnc/passwd" -localhost -forever -shared -quiet &
    websockify --web /usr/share/novnc 6080 127.0.0.1:5900 >/dev/null 2>&1 &
fi
unset VNC_PASSWORD

# Use srt nested mode inside the container
export OPENMUSE_HEADLESS=1 OPENMUSE_SRT_NESTED=1
if [ -n "${DEVICE_CODE:-}" ]; then
    code="$DEVICE_CODE"
    unset DEVICE_CODE
    config="$HOME/.openmuse/device.json"
    pair=1
    if [ -f "$config" ]; then
        saved="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("code_hash", ""))' "$config" 2>/dev/null || true)"
        if [ -z "$saved" ]; then
            echo "Existing pairing found; ignoring DEVICE_CODE. To use a new pairing code, use a different volume or delete ~/.openmuse/device.json" >&2
            pair=0
        elif [ "$saved" = "$(printf '%s' "$code" | sha256sum | cut -d' ' -f1)" ]; then
            pair=0
        else
            echo "DEVICE_CODE differs from the saved pairing; pairing again with the new code" >&2
        fi
    fi
    if [ "$pair" = 1 ]; then
        exec /opt/openmuse-device/start-device.sh --server "${DEVICE_SERVER:?Please set DEVICE_SERVER}" --code "$code"
    fi
fi
if [ -n "${DEVICE_TOKEN:-}" ]; then
    # Pass the token only via environment variable, never on the command line
    export WORK_AGENT_DEVICE_TOKEN="$DEVICE_TOKEN"
    unset DEVICE_TOKEN
    export OPENMUSE_SERVER="$DEVICE_URL" OPENMUSE_DEVICE="$DEVICE_NAME"
fi
exec /opt/openmuse-device/start-device.sh
