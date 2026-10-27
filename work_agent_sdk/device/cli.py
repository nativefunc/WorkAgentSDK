from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any

from work_agent_sdk.device.server import DeviceDaemon
from work_agent_sdk.host.screen.policy import DeviceCeiling


def read_token(arguments: argparse.Namespace) -> str:
    if arguments.token_file:
        with open(os.path.expanduser(arguments.token_file)) as file:
            return file.read().strip()

    token = arguments.token or os.environ.get("WORK_AGENT_DEVICE_TOKEN")
    if not token:
        raise ValueError("Missing token; provide it with --token, --token-file or the WORK_AGENT_DEVICE_TOKEN environment variable")
    return token


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m work_agent_sdk.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    node = commands.add_parser("device", help="Connect this machine to the backend as a device")
    node.add_argument("--name", required=True, help="Device name; must match the one registered on the backend")
    node.add_argument("--url", help="Used when the device connects to the backend: the backend's endpoint, e.g. wss://myapp.com/work_agent_sdk/nodes")
    node.add_argument("--listen", help="Used when waiting for the backend to connect: address to listen on, e.g. 127.0.0.1:7000")
    node.add_argument("--tls-cert", help="Certificate for TLS on --listen; when set, the backend connects with wss://")
    node.add_argument("--tls-key", help="Private key for TLS on --listen")
    node.add_argument("--token", help="Token (can also be given with --token-file or the WORK_AGENT_DEVICE_TOKEN environment variable)")
    node.add_argument("--token-file", help="Read the token from a file")
    node.add_argument(
        "--workspace", action="append", default=[], help="Directory to expose (the backend can read and write files and place workspaces in it); may be given multiple times"
    )
    node.add_argument(
        "--protect",
        choices=["standard", "none"],
        default="standard",
        help="Protection template: standard (default) blocks the backend from writing auto-executed files such as shell startup files and git hooks, and blocks reads of credential directories; none disables it",
    )
    node.add_argument(
        "--sandbox",
        choices=["srt", "none"],
        help="Allow running commands in the exposed directories and choose the sandbox; when unset, files can only be read and written",
    )
    node.add_argument(
        "--network",
        default=None,
        help="Upper bound on domains the sandbox may reach, comma-separated; no bound when unset, and the backend decides which domains to allow",
    )
    node.add_argument("--allow-unsandboxed", action="store_true", help="Allow commands approved by the backend to run outside the sandbox")
    node.add_argument("--srt-binary", default="srt", help="Name or path of the srt sandbox program (default: look up srt in PATH)")
    node.add_argument("--srt-nested", action="store_true", help="Running inside a container: use srt's weaker nested sandbox mode")
    node.add_argument("--srt-settings", default=None, help="Extra settings passed to srt as is (path to a JSON file)")
    node.add_argument("--env", action="append", default=[], help="Name of a local environment variable to also pass to commands; may be given multiple times")
    node.add_argument("--screen", action="store_true", help="Expose the screen")
    node.add_argument(
        "--screen-deny", action="append", default=[], help="Apps that may not be operated (id, name or program name; supports the * wildcard)"
    )
    node.add_argument(
        "--screen-max-tier",
        choices=["view", "click", "full"],
        default="full",
        help="Highest access tier allowed",
    )
    node.add_argument(
        "--display",
        action="append",
        default=[],
        help="Linux X display number to expose to the backend, e.g. :1; may be given multiple times",
    )
    node.add_argument("--browser", action="store_true", help="Allow the backend to launch a browser on this device")
    node.add_argument("--headless", action="store_true", help="Unattended screen (container, cloud desktop): don't register the Esc emergency stop")
    node.add_argument("--disconnect-grace", type=float, default=None, help="Maximum seconds commands are kept after a disconnect")
    node.add_argument(
        "--audit-log",
        default=None,
        help="Log the backend's operations on this device to this file (JSON Lines format, readable only by the local user)",
    )
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    network: list[str] | None = None
    if arguments.network is not None:
        network = [domain.strip() for domain in arguments.network.split(",") if domain.strip()]

    srt_settings: dict[str, Any] = {}
    if arguments.srt_settings:
        with open(os.path.expanduser(arguments.srt_settings)) as file:
            srt_settings = json.load(file)

    try:
        if bool(arguments.url) == bool(arguments.listen):
            raise ValueError("Exactly one of --url and --listen must be specified")

        device = DeviceDaemon(
            name=arguments.name,
            token=read_token(arguments),
            workspace=list(arguments.workspace),
            protect=arguments.protect,
            sandbox=arguments.sandbox,
            network=network,
            allow_unsandboxed=arguments.allow_unsandboxed,
            srt_binary=arguments.srt_binary,
            srt_nested=arguments.srt_nested,
            srt_settings=srt_settings,
            env=arguments.env,
            screen=arguments.screen,
            screen_ceiling=DeviceCeiling(arguments.screen_deny, arguments.screen_max_tier),
            displays=arguments.display,
            browser=arguments.browser,
            esc_stop=arguments.screen and not arguments.headless,
            grace=arguments.disconnect_grace,
            audit_log=arguments.audit_log,
        )
        if arguments.url:
            asyncio.run(device.run_forever(arguments.url))
        else:
            host, _, port = arguments.listen.rpartition(":")
            asyncio.run(
                device.listen(host or "127.0.0.1", int(port), tls_cert=arguments.tls_cert, tls_key=arguments.tls_key)
            )
    except KeyboardInterrupt:
        pass
    except (PermissionError, ValueError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
