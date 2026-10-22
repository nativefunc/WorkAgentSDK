from __future__ import annotations

TOOL_DEFAULT_DESCRIPTION = "MCP 工具 {name}"
TOOL_ERROR = "MCP 工具返回错误"
AUDIO_TOO_LARGE = "[音频超过 {limit} MB，未保存]"

# 未授权时替代该服务全部工具的授权工具
AUTHORIZE_DESCRIPTION = "{server} 尚未授权。用户需要使用 {server} 的功能时调用此工具，请用户完成授权。"
AUTHORIZED = "用户已完成 {server} 的授权，现在可以使用其工具。"

LIST_RESOURCES_DESCRIPTION = "列出 MCP 服务 {server} 提供的资源。"
NO_RESOURCES = "无资源"
READ_RESOURCE_DESCRIPTION = "读取 MCP 服务 {server} 的一个资源。"
RESOURCE_URI = "资源 URI"
BINARY_RESOURCE = "[二进制资源 {uri}，类型 {mime}]"
