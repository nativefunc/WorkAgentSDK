<div align="center">

# Work Agent SDK

[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Claude](https://img.shields.io/badge/Claude-supported-D97757?logo=anthropic&logoColor=white)](https://docs.anthropic.com/)
[![OpenAI](https://img.shields.io/badge/OpenAI-supported-412991?logo=openai&logoColor=white)](https://platform.openai.com/docs)
[![Qwen](https://img.shields.io/badge/Qwen-supported-615CED)](https://help.aliyun.com/zh/model-studio/)
[![MCP](https://img.shields.io/badge/MCP-supported-000000)](https://modelcontextprotocol.io/)
[![Sandbox](https://img.shields.io/badge/sandbox-srt-2EA44F)](https://github.com/anthropic-experimental/sandbox-runtime)

<!-- 填入仓库地址后启用：
[![stars](https://img.shields.io/github/stars/OWNER/REPO?style=flat)](https://github.com/OWNER/REPO)
[![forks](https://img.shields.io/github/forks/OWNER/REPO?style=flat)](https://github.com/OWNER/REPO)
[![issues](https://img.shields.io/github/issues/OWNER/REPO)](https://github.com/OWNER/REPO/issues)
[![license](https://img.shields.io/github/license/OWNER/REPO)](LICENSE)
-->

</div>

## 项目简介

Work Agent SDK 是一个 Python 智能体框架。智能体可以在沙箱中执行命令，操作浏览器和电脑，也可以连接远程设备工作；遇到需要人决定的事，会暂停并等待审批或接管，答复后从原处继续。

## 主要功能

- **工具**：普通函数加上 `@tool` 即成为工具。内置 Shell、浏览器、电脑操作、MCP、技能、子智能体和定时任务
- **沙箱**：命令在 [srt](https://github.com/anthropic-experimental/sandbox-runtime) 沙箱中执行，可写目录和可访问的域名由配置决定
- **远程设备**：其他机器运行一条命令即可接入。开放哪些目录、能否执行命令、能否操作屏幕，都由设备所有者决定
- **人工介入**：审批、接管浏览器或电脑、由前端执行的工具，答复后从原处继续
- **可恢复**：会话持久化保存，后端重启后从中断处继续
- **多模型**：Claude、OpenAI、千问，以及兼容 OpenAI 接口的服务

## 快速开始

### 安装

在源码根目录执行（需要 Python 3.11+）：

```bash
pip install . -r requirements.txt
```

### 第一个智能体

```bash
export ANTHROPIC_API_KEY=...
```

```python
import asyncio

from work_agent_sdk import Agent, Runner, tool
from work_agent_sdk.models import Claude


@tool(description="两数相加")
def add(a: int, b: int) -> int:
    return a + b


agent = Agent("main", model=Claude("claude-sonnet-4-5"), tools=[add])


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session()
        result = await session.send("2 加 3 等于几？")
        print(result.text)


asyncio.run(main())
```

## 示例

可以直接运行的示例见 [examples](examples/)：工具、结构化输出、流式输出、人工审批、钩子、工作区、子智能体、MCP、定时任务、浏览器、电脑操作、远程设备、Web 后端、接入外部 webhook 等。

## 开发

需要另外安装 `pytest` 和 `ruff`：

```bash
python -m pytest
ruff format work_agent_sdk tests
ruff check work_agent_sdk tests
```
