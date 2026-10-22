# 示例

每个示例都是一个可以直接运行的脚本，按由浅入深排列。

## 运行

在源码根目录安装框架，并设置密钥：

```bash
pip install . -r requirements.txt
export ANTHROPIC_API_KEY=...
python examples/01_hello.py
```

`29_custom_model.py` 不调用真实模型，不需要密钥。带目录的示例（如 `30_web_backend/`）进入目录后按文件开头的说明运行。

## 基础

| 示例 | 内容 |
| --- | --- |
| [01_hello.py](01_hello.py) | 最小的智能体，多轮对话 |
| [02_tools.py](02_tools.py) | 函数工具：参数说明、返回数据、返回错误、把完整数据单独交给前端 |
| [03_toolsets.py](03_toolsets.py) | 工具集：按会话提供不同的工具、筛选工具、按需加载大量工具（ToolSearch） |
| [04_structured_output.py](04_structured_output.py) | 让智能体返回 pydantic 对象 |
| [05_streaming.py](05_streaming.py) | 逐段打印回答，显示工具调用 |
| [06_sessions.py](06_sessions.py) | 会话：重启后重新打开、加入应用自己的消息、消息排队与优先级、撤回、复制 |
| [07_models.py](07_models.py) | 思考强度、模型参数、按租户使用不同密钥、对话中切换模型、单独调用模型 |
| [08_providers.py](08_providers.py) | 接入 Claude、OpenAI、DeepSeek、智谱、千问 |

## 人工介入

| 示例 | 内容 |
| --- | --- |
| [09_approval.py](09_approval.py) | 部署前在终端请用户确认 |
| [10_requests.py](10_requests.py) | 自定义请求、由前端执行的工具、等待外部系统回调、输入密码 |
| [11_hooks.py](11_hooks.py) | 钩子：拒绝消息、换用模型、拦截工具调用、审计日志、让模型继续、模型出错时换用备用模型 |

## 环境

| 示例 | 内容 |
| --- | --- |
| [12_workspace.py](12_workspace.py) | 工作区：智能体写代码、运行命令；应用直接读写文件、执行命令、管理后台进程。需要 srt |
| [13_sandbox.py](13_sandbox.py) | 沙箱：调整可读写的路径和网络，在沙箱外执行命令前请用户批准。需要 srt |
| [14_browser.py](14_browser.py) | 浏览器：网址规则、保持登录状态、在代码中操作浏览器。需要 Playwright |
| [15_browser_cdp.py](15_browser_cdp.py) | 连接用户已在运行的 Chrome，沿用其中的登录状态 |
| [16_computer.py](16_computer.py) | 电脑操作：授权应用、处理接管请求。需要桌面环境 |
| [17_device_connect/](17_device_connect/backend.py) | 远程设备主动连接后端：为每个用户签发令牌，智能体在用户的电脑上工作。需要 FastAPI |
| [18_device_listen.py](18_device_listen.py) | 后端连接远程设备 |
| [19_shared_folder.py](19_shared_folder.py) | 共享文件夹：同一份数据在不同机器上的路径 |
| [20_isolated_env.py](20_isolated_env.py) | 为每个会话启动一个 Docker 容器，会话关闭时删除 |

## 扩展

| 示例 | 内容 |
| --- | --- |
| [21_subagents.py](21_subagents.py) | 子智能体：前台、后台、动态 |
| [22_subagent_tasks.py](22_subagent_tasks.py) | 在工具和应用代码中创建子会话 |
| [23_mcp.py](23_mcp.py) | MCP：远程服务、本地服务、在工作区中启动 |
| [24_mcp_oauth/](24_mcp_oauth/app.py) | 需要 OAuth 登录的 MCP 服务。需要 FastAPI |
| [25_skills/](25_skills/main.py) | 技能：按需加载说明，运行技能附带的脚本 |
| [26_schedules.py](26_schedules.py) | 定时任务：模型创建任务、代码管理任务、接收定时任务触发的输出 |

## 进阶

| 示例 | 内容 |
| --- | --- |
| [27_custom_service.py](27_custom_service.py) | 自定义服务：为每个会话提供资源、把资源状态告诉模型、后台任务通知会话 |
| [28_storage.py](28_storage.py) | 替换会话存储，用自定义密钥加密 OAuth 令牌 |
| [29_custom_model.py](29_custom_model.py) | 自定义模型 |
| [30_web_backend/](30_web_backend/app.py) | FastAPI 后端和网页：发送消息、SSE 实时输出、在网页上审批 |
| [31_webhook/](31_webhook/app.py) | 接入外部 webhook：把外部系统的事件作为 CustomMessage 告诉智能体，进行中的消息更新进度，需要时让智能体立即处理 |
| [32_takeover/](32_takeover/app.py) | 用户接管浏览器或电脑：推送实时画面、转发用户操作 |
