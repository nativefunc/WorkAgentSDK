"""浏览器：框架在本机启动浏览器，智能体打开网页、点击、输入、读取内容。

运行前需要安装 Playwright 和浏览器：
    pip install playwright
    playwright install chromium     # 本机已安装 Chrome 或 Edge 时可以省略
"""

import asyncio
from pathlib import Path

from work_agent_sdk import Agent, Browser, BrowserPolicy, BrowserUse, Runner
from work_agent_sdk.models import Claude

agent = Agent(
    "researcher",
    model=Claude("claude-sonnet-4-5"),
    instructions="你是研究助手，用浏览器查找资料，回答时给出来源网址。",
    tools=[BrowserUse()],
)

browser = Browser(
    node="local",
    headless=False,  # 显示浏览器窗口，便于观察
    profile="research",  # 使用同一 profile 的会话共用登录状态，长期保存在本机
    policy=BrowserPolicy.standard(
        deny=["*.facebook.com"],  # 禁止访问的网站
        private=["127.0.0.1:*"],  # 默认禁止访问本机和内网地址，这里放行本机的服务
    ),
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(browser=browser)

        result = await session.send("打开 https://www.python.org ，告诉我最新的 Python 版本号。")
        print(result.text)

        # 应用也可以直接操作会话的浏览器
        bound = await session.browser()
        page = await bound.perform("get_page_text", {})
        print(page["text"][:200])
        Path("python-org.jpg").write_bytes(await bound.screenshot())

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
