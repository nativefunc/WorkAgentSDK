"""电脑操作：智能体通过截图、点击和输入操作桌面应用。

运行前的准备：
    Linux：需要 X 桌面，并安装 xdotool、x11-utils、imagemagick
    macOS：为运行脚本的终端开启"辅助功能"和"屏幕录制"权限，并 pip install pyautogui
    所有系统：pip install Pillow
"""

import asyncio

from work_agent_sdk import Agent, Computer, ComputerUse, Runner
from work_agent_sdk.models import Claude

agent = Agent(
    "operator",
    model=Claude("claude-sonnet-4-5"),
    instructions="你通过截图和鼠标键盘操作电脑上的应用。",
    tools=[ComputerUse()],
)


async def main():
    async with Runner(agents=[agent]) as runner:
        session = await runner.new_session(computer=Computer(node="local"))

        result = await session.send("打开系统自带的文本编辑器，新建一个文件，写入：明天上午十点开会。")
        while result.status == "waiting":
            request = result.pending[0]
            if request.type == "AppAccess":
                apps = "、".join(app["name"] for app in request.data["apps"])
                reply = input(f"智能体申请操作 {apps}（{request.data['reason']}），是否允许？[y/N] ")
                answer = {"approved": reply.strip().lower() == "y"}
            else:
                # Takeover：智能体遇到自己无法完成的操作，请用户在电脑上手动处理
                input(f"需要你手动处理：{request.data['reason']}。完成后按回车继续")
                answer = {"done": True}
            result = await session.answer(request.id, answer)

        print(result.text)
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
