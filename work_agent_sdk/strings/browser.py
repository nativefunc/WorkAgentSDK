from __future__ import annotations

ACTIONS = {
    "navigate": "打开网址，或执行 back、forward、reload。",
    "screenshot": "截取当前页面的可见区域。",
    "zoom": "放大查看页面上的指定区域。",
    "left_click": "左键单击元素或坐标。",
    "right_click": "右键单击。",
    "middle_click": "中键单击。",
    "double_click": "双击。",
    "triple_click": "三击。",
    "hover": "将鼠标悬停在目标上。",
    "left_click_drag": "从一个坐标拖动到另一个坐标。",
    "left_mouse_down": "在坐标处按下左键。",
    "left_mouse_up": "在坐标处松开左键。",
    "mouse_move": "移动鼠标。",
    "scroll": "在坐标处滚动。",
    "scroll_to": "将元素滚动到可见区域。",
    "type": "在当前焦点处输入文字。不得向密码、银行卡或验证码输入框输入；需要登录时，请使用 browser_takeover 请用户接管。",
    "key": "按下按键。",
    "hold_key": "按住某个键一段时间。",
    "wait": "等待一段时间。",
    "read_page": "读取页面结构，包括元素及其 ref。操作元素时请使用 ref。",
    "find": "按文字查找元素，最多返回 20 个。",
    "get_page_text": "获取页面的全部可见文字。",
    "form_input": "设置表单元素的值（输入框、下拉框、复选框）。",
    "file_upload": "将工作区中的文件上传到页面的文件输入框。",
    "read_console": "读取页面的控制台日志。",
    "read_network": "读取页面最近的网络请求。",
    "javascript_exec": "在页面中执行 JavaScript 并返回结果。",
    "new_tab": "打开新标签页。",
    "list_tabs": "列出全部标签页。",
    "switch_tab": "切换到指定标签页。",
    "close_tab": "关闭指定标签页。",
}

TAB_ID = "标签页 id；省略时为当前标签页"
REF = "read_page 或 find 返回的 ref，例如 ref_2"
TARGET = "坐标或元素 ref"
MODIFIERS = "按住的修饰键，例如 shift、ctrl+shift"
URL = "网址，或 back、forward、reload"
SCROLL_AMOUNT = "滚动量，取值 1 到 10，默认 3"
KEY_TEXT = "单个按键（如 Enter）、组合键（如 ctrl+a），或以空格分隔的按键序列（如 Backspace Backspace）"
WAIT_DURATION = "等待秒数，取值 0 到 30"
READ_FILTER = "interactive 只返回可操作的元素，all 返回全部元素"
READ_REF = "仅读取该元素内部的内容"
FIND_QUERY = "要查找的文字"
UPLOAD_PATHS = "浏览器所在节点上的文件或文件夹路径"
JAVASCRIPT = "要在页面中执行的 JavaScript 代码"

REQUESTS_BLOCKED = "网址规则拦截了 {count} 个请求，页面可能显示不完整。"
USER_ACTED = "自上次操作以来，用户操作过标签页 {tabs}，页面可能已发生变化。"
DONE = "已完成。"

TAKEOVER_DESCRIPTION = (
    "请求用户接管浏览器。在需要登录、输入密码或验证码、确认付款，或遇到无法自行完成的操作时调用。"
    "用户完成操作后会返回结果，届时请先重新查看页面再继续。"
)
TAKEOVER_REASON = "需要用户完成的操作及原因"
TAKEOVER_DONE = "用户已完成操作。请先重新查看页面，再继续执行。"

SCREENSHOT = "截图（{width}x{height}）："
NAVIGATE_BLOCKED = "网址规则不允许打开该网址或其跳转地址：{urls}"
NAVIGATE_FAILED = "打开失败：{error}"
OPENED = "已打开 {url}"
ZOOM_REGION = "[x0, y0, x1, y1]：要放大的矩形区域，左上角 (x0, y0) 到右下角 (x1, y1)，与截图同一坐标系"
ZOOM_EMPTY = "zoom 指定的区域为空"
CLICKED_REF = "已点击 {ref}"
CLICKED_POINT = "已点击该位置"
HOVERED = "已悬停"
DRAGGED = "已拖动"
MOUSE_DOWN = "已按下左键"
MOUSE_UP = "已松开左键"
MOUSE_MOVED = "已移动鼠标"
SCROLLED = "已滚动"
SCROLLED_TO = "已滚动到 {ref}"
SENSITIVE_FOCUS = "焦点位于密码、银行卡或验证码输入框，不允许输入。需要登录或付款时，请使用 browser_takeover 请用户接管"
SENSITIVE_FIELD = "不允许填写密码、银行卡或验证码输入框。需要登录或付款时，请使用 browser_takeover 请用户接管"
TYPED = "已输入"
KEY_PRESSED = "已按键"
KEY_RELEASED = "已松开按键"
WAITED = "等待完成"
PAGE = "页面：{title} — {url}\n{text}"
PAGE_EMPTY = "（无内容）"
NOT_FOUND = "未找到匹配的元素"
NO_TEXT = "（页面无文字）"
FIELD_SET = "已设置 {ref}"
UPLOADED = "已上传 {count} 个文件"
NO_CONSOLE = "（无控制台日志）"
NO_NETWORK = "（无网络请求记录）"
SCRIPT_FAILED = "执行出错：{error}"
TAB_OPENED = "已打开新标签页 {tab}，并设为当前标签页"
NO_TABS = "（无标签页）"
TAB_SWITCHED = "已切换到 {tab}"
TAB_CLOSED = "已关闭 {tab}"

FACTS_ON_NODE = "浏览器：节点 {node} 上的浏览器"
FACTS_EXTERNAL = "浏览器：外部浏览器"
FACTS_OWN_BROWSER = "（用户自己的浏览器，已打开的标签页归当前会话使用）"
FACTS_DOWNLOAD_DIR = "下载保存在 {path}。"
FACTS_DOWNLOAD_DIR_TEMPORARY = "下载保存在 {path}，会话结束时删除。"
FACTS_DOWNLOAD_DIR_DEFAULT = "下载保存在该节点上框架的下载目录，会话结束时删除。"
FACTS_DOWNLOADS_BY_BROWSER = "下载由浏览器按自身设置保存。"
FACTS_DOWNLOADS_DENIED = "该浏览器不接受下载。"
FACTS_SHARED_FOLDER = "共享文件夹 {name} 在该节点上位于 {path}。"
FACTS_OFFLINE = "浏览器所在的节点当前离线，使用时将等待其重新连接。"
FACTS_DESCRIPTION = "说明：{description}"

DOWNLOAD_COMPLETED = "下载完成：{name}，保存在 {path}。"
DOWNLOAD_COMPLETED_BY_BROWSER = "下载完成：{name}。"
DOWNLOAD_FAILED = "下载失败：{name}：{error}"

UPLOAD_NO_NODE = "浏览器没有所在节点，无法上传文件"
UPLOAD_NOT_ABSOLUTE = "{path} 须为浏览器所在节点上的绝对路径"
UPLOAD_NOT_FOUND = "{path} 在浏览器所在节点上不存在"
UPLOAD_NOT_ALLOWED = "{path} 不在可上传的位置"
UPLOAD_SANDBOX = "沙箱规则不允许读取 {path}"
UPLOAD_ONE_DIRECTORY = "一次只能上传一个文件夹，且不能同时上传文件"
UPLOAD_NO_DIRECTORY = "该上传框不接受文件夹"
UPLOAD_SINGLE = "该上传框只接受一个文件"
