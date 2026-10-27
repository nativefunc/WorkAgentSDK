from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: python -m work_agent_sdk.cli device [options]    Run the device daemon (see python -m work_agent_sdk.cli device --help for options)"
        )
        return
    if args[0] == "device":
        from work_agent_sdk.device.cli import main as device_main

        device_main(args)
        return

    print(f"Unknown command: {args[0]}", file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
