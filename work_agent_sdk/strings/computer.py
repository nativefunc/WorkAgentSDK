from __future__ import annotations

# 应用授权级别的说明，在授权请求中展示给用户
TIER_WARNINGS = {
    "click": "终端、IDE：仅可点击和滚动，不可输入（输入等同于执行命令）",
    "view": "浏览器、交易软件：仅可查看",
}

ACTIONS = {
    "screenshot": "截取屏幕。",
    "zoom": "放大查看屏幕上的指定区域。",
    "left_click": "左键单击。",
    "right_click": "右键单击。",
    "middle_click": "中键单击。",
    "double_click": "双击。",
    "triple_click": "三击（选中整行）。",
    "left_click_drag": "按住左键，从 start_coordinate 拖动到 coordinate。",
    "mouse_move": "移动鼠标。",
    "left_mouse_down": "按下左键（不松开）。",
    "left_mouse_up": "松开左键。",
    "cursor_position": "获取鼠标当前位置。",
    "scroll": "滚动。",
    "type": "输入文字。",
    "key": "按下按键或组合键。",
    "hold_key": "按住某个键一段时间。",
    "wait": "等待一段时间。",
}
MODIFIERS = "点击时按住的修饰键：shift、ctrl、alt、super，或以 + 连接，例如 ctrl+shift"
COORDINATE = "[x, y]，以截图像素表示；省略时在鼠标当前位置点击"
ZOOM_REGION = "[x0, y0, x1, y1]：要放大的矩形区域，左上角 (x0, y0) 到右下角 (x1, y1)，与截图同一坐标系"
SCROLL_AMOUNT = "滚轮格数"
TYPE_TEXT = "要输入的文字"
KEY_TEXT = "按键或组合键，例如 Return、ctrl+s、alt+Tab"
KEY_REPEAT = "重复次数，取值 1 到 100"
DURATION = "秒数，最大 300"

BATCH_DESCRIPTION = "按顺序执行一组电脑操作，并返回执行后的截图。"
TAKEOVER_DESCRIPTION = (
    "请求用户接管电脑。在需要输入密码、验证码，或遇到无法自行完成的操作时调用；用户完成后会返回结果。"
)
REQUEST_ACCESS_DESCRIPTION = (
    "申请操作电脑上的应用，用户同意后在当前会话中持续有效。操作未授权的应用会被拒绝，请先通过本工具申请。"
    "终端和 IDE 获得授权后也仅可点击和滚动；浏览器和交易软件仅可查看。"
)
LIST_APPS_DESCRIPTION = "列出已授权的应用及其可操作的级别、正在运行的应用，以及当前的前台应用。"
OPEN_APP_DESCRIPTION = (
    "打开应用；应用已在运行时将其切到前台。完成后返回截图。在 standard 模式下，只能打开已授权的应用。"
)

ACCESS_APPS = '要操作的应用名称，例如 ["Microsoft Word"]；已安装但未运行的应用也可申请'
ACCESS_REASON = "向用户说明为何需要操作这些应用"
ACCESS_SYSTEM_KEYS = "是否还需要使用系统组合键（如切换应用、退出应用）"
TAKEOVER_REASON = "需要用户完成的操作及原因"
OPEN_APP_APP = "应用名称或身份，例如 Microsoft Word、com.apple.TextEdit"

CURSOR_POSITION = "鼠标位置：({x}, {y})"
DONE = "已完成"
SCREENSHOT = "截图（{width}x{height}）："
WAITED_FOR = "（电脑此前被会话 {session} 占用，待其释放后才执行，画面可能与上次所见不同）"
USER_ACTED = "（自上次操作以来，用户操作过该电脑，画面可能与上次所见不同）"
BUSY = "电脑正被会话 {session} 使用，等待 {seconds} 秒后仍未释放；请稍后重试，或先处理其他工作"
TAKEOVER_DONE = "用户已完成操作。请先重新截图查看，再继续执行。"
APP_OPENED = "{app} 已在前台。截图："

ACCESS_REFUSED = "不允许操作：{apps}"
ACCESS_MISSING = "未找到应用：{apps}（既未在运行，也未安装）"
ACCESS_ALREADY_GRANTED = "其余应用已可操作"
ACCESS_NOTHING = "没有需要申请的应用"
ACCESS_DENIED = "用户未同意{note}"
ACCESS_GRANTED = "用户已同意：{granted}"
SYSTEM_KEYS = "系统组合键"

APPS_TITLE = "已授权的应用（应用：级别）："
APPS_DEVELOPER = "- {app}：{tier}（开发者设置）"
APPS_BY_TYPE = "按应用类型"
APPS_GRANTED = "- {app}：{tier}"
APPS_SYSTEM_KEYS = "系统组合键：已授权"
APPS_RUNNING = "正在运行的应用：{apps}"
APPS_FRONTMOST = "前台应用：{app}"

FACTS_SCREEN = "电脑：节点 {node} 的屏幕。"
FACTS_RESTRICTED = "仅可操作已授权的应用；未授权的应用请先通过 computer_request_access 申请。"
FACTS_OFFLINE = "该节点当前离线，使用时将等待其重新连接。"
FACTS_SHARED_FOLDER = "共享文件夹 {name} 在该节点上位于 {path}。"
FACTS_DESCRIPTION = "说明：{description}"
