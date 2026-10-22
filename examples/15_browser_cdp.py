"""连接已在运行的浏览器：通过 CDP 连接用户自己的 Chrome，沿用其中的登录状态。

先用调试端口启动 Chrome（启动前关闭所有 Chrome 窗口）：
    macOS：  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222
    Linux：  google-chrome --remote-debugging-port=9222
    Windows："C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222
在这个 Chrome 中登录需要的网站，然后运行本例。
"""

import asyncio

from work_agent_sdk import Agent, Browser, BrowserUse, Runner
from work_agent_sdk.models import Claude

agent = Agent(
    "assistant",
    model=Claude("claude-sonnet-4-5"),
    instructions="你在用户自己的浏览器中操作，浏览器已登录用户的账号。",
    tools=[BrowserUse()],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(
            # profile="shared"：使用这个浏览器现有的登录状态和 Cookie，已打开的标签页也交给智能体
            browser=Browser(cdp="http://127.0.0.1:9222", profile="shared"),
        )

        result = await session.send("看一下我已经打开了哪些标签页，总结每个页面的主要内容。")
        print(result.text)

        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
