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
        raise ValueError("缺少令牌；请通过 --token、--token-file 或环境变量 WORK_AGENT_DEVICE_TOKEN 提供")
    return token


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m work_agent_sdk.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    node = commands.add_parser("device", help="将本机作为设备接入后端")
    node.add_argument("--name", required=True, help="设备名称，须与后端登记的一致")
    node.add_argument("--url", help="设备主动连接后端时使用：后端的接入地址，如 wss://myapp.com/work_agent_sdk/nodes")
    node.add_argument("--listen", help="等待后端连接时使用：监听地址，如 127.0.0.1:7000")
    node.add_argument("--tls-cert", help="--listen 监听非回环地址时使用的证书")
    node.add_argument("--tls-key", help="--listen 监听非回环地址时使用的私钥")
    node.add_argument("--token", help="令牌（也可通过 --token-file 或环境变量 WORK_AGENT_DEVICE_TOKEN 提供）")
    node.add_argument("--token-file", help="从文件读取令牌")
    node.add_argument(
        "--workspace", action="append", default=[], help="开放的目录（后端可在其中读写文件、放置工作区），可指定多次"
    )
    node.add_argument(
        "--protect",
        choices=["standard", "none"],
        default="standard",
        help="保护模板：standard（默认）禁止后端写入 shell 启动文件、git 钩子等会被自动执行的文件，并禁止读取凭据目录；none 不启用",
    )
    node.add_argument(
        "--sandbox",
        choices=["srt", "none"],
        help="允许在开放目录中执行命令并指定所用沙箱；未指定时仅可读写文件",
    )
    node.add_argument("--network", default=None, help="沙箱允许访问的域名，以逗号分隔")
    node.add_argument("--allow-unsandboxed", action="store_true", help="允许后端审批过的命令在沙箱外执行")
    node.add_argument("--srt-binary", default="srt", help="srt 沙箱程序名或路径（默认在 PATH 中查找 srt）")
    node.add_argument("--srt-nested", action="store_true", help="在容器内运行：使用 srt 较弱的嵌套沙箱模式")
    node.add_argument("--srt-settings", default=None, help="原样传给 srt 的额外配置（JSON 文件路径）")
    node.add_argument("--env", action="append", default=[], help="额外传递给命令的本机环境变量名，可指定多次")
    node.add_argument("--screen", action="store_true", help="开放屏幕")
    node.add_argument(
        "--screen-deny", action="append", default=[], help="禁止操作的应用（id、名称或程序名，支持 * 通配）"
    )
    node.add_argument("--screen-max-tier", choices=["view", "click", "full"], default="full", help="允许的最高操作级别")
    node.add_argument("--display", action="append", default=[], help="开放给后端的 Linux X 桌面编号，如 :1，可指定多次")
    node.add_argument("--browser", action="store_true", help="允许后端在本设备上启动浏览器")
    node.add_argument("--headless", action="store_true", help="无人值守的屏幕（容器、云电脑）：不注册 Esc 急停")
    node.add_argument("--disconnect-grace", type=float, default=None, help="断线后命令最多保留的秒数")
    node.add_argument(
        "--audit-log",
        default=None,
        help="将后端在本设备上的操作记录到该文件（JSON Lines 格式，仅本机用户可读）",
    )
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    network: bool | list[str] = True
    if arguments.network is not None:
        network = [domain.strip() for domain in arguments.network.split(",") if domain.strip()]

    srt_settings: dict[str, Any] = {}
    if arguments.srt_settings:
        with open(os.path.expanduser(arguments.srt_settings)) as file:
            srt_settings = json.load(file)

    try:
        if bool(arguments.url) == bool(arguments.listen):
            raise ValueError("--url 与 --listen 须且仅须指定其一")

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
