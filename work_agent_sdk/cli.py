from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(
            "用法：python -m work_agent_sdk.cli device [选项]    运行设备守护进程（使用 python -m work_agent_sdk.cli device --help 查看选项）"
        )
        return
    if args[0] == "device":
        from work_agent_sdk.device.cli import main as device_main

        device_main(args)
        return

    print(f"未知的命令：{args[0]}", file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
