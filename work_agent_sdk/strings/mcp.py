from __future__ import annotations

TOOL_DEFAULT_DESCRIPTION = "MCP tool {name}"
TOOL_ERROR = "The MCP tool returned an error"
AUDIO_TOO_LARGE = "[Audio larger than {limit} MB, not saved]"

# Authorization tool that replaces all of a server's tools while it's unauthorized
AUTHORIZE_DESCRIPTION = "{server} is not yet authorized. Call this tool when the user needs {server}'s features, to ask the user to complete authorization."
AUTHORIZED = "The user has authorized {server}; its tools can be used now."

LIST_RESOURCES_DESCRIPTION = "List the resources provided by MCP server {server}."
NO_RESOURCES = "No resources"
READ_RESOURCE_DESCRIPTION = "Read a resource from MCP server {server}."
RESOURCE_URI = "Resource URI"
BINARY_RESOURCE = "[Binary resource {uri}, type {mime}]"
