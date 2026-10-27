#!/bin/sh

set -e

if [ -z "$DEVICE_NAME" ] || [ -z "$DEVICE_TOKEN" ]; then
    echo "Please set DEVICE_NAME and DEVICE_TOKEN" >&2
    exit 1
fi

export WORK_AGENT_DEVICE_TOKEN="$DEVICE_TOKEN"
unset DEVICE_TOKEN

if [ -n "$DEVICE_URL" ]; then
    set -- --url "$DEVICE_URL" "$@"
else
    set -- --listen "$DEVICE_LISTEN" "$@"
fi

if [ -n "$DEVICE_AUDIT_LOG" ]; then
    set -- --audit-log "$DEVICE_AUDIT_LOG" "$@"
fi

if [ "$DEVICE_SANDBOX" = "srt" ]; then
    set -- --srt-nested "$@"

    if [ -n "$DEVICE_NETWORK" ]; then
        set -- --network "$DEVICE_NETWORK" "$@"
    fi
fi

exec python -m work_agent_sdk.cli device --name "$DEVICE_NAME" \
    --workspace "$DEVICE_WORKSPACE" --sandbox "$DEVICE_SANDBOX" "$@"
