from __future__ import annotations

ACTIONS = {
    "navigate": "Open a URL, or perform back, forward or reload.",
    "screenshot": "Take a screenshot of the visible area of the current page.",
    "zoom": "Zoom in on a region of the page.",
    "left_click": "Left-click an element or coordinate.",
    "right_click": "Right-click.",
    "middle_click": "Middle-click.",
    "double_click": "Double-click.",
    "triple_click": "Triple-click.",
    "hover": "Hover the mouse over the target.",
    "left_click_drag": "Drag from one coordinate to another.",
    "left_mouse_down": "Press the left button at a coordinate.",
    "left_mouse_up": "Release the left button at a coordinate.",
    "mouse_move": "Move the mouse.",
    "scroll": "Scroll at a coordinate.",
    "scroll_to": "Scroll an element into view.",
    "type": "Type text at the current focus.",
    "key": "Press keys.",
    "hold_key": "Hold a key down for a period of time.",
    "wait": "Wait for a period of time.",
    "read_page": "Read the page structure, including elements and their refs. Use refs to act on elements.",
    "find": "Find elements by text; returns at most 20.",
    "get_page_text": "Get all visible text on the page.",
    "form_input": "Set the value of a form element (input, select, checkbox).",
    "file_upload": "Upload files to a file input on the page.",
    "read_console": "Read the page's console logs.",
    "read_network": "Read the page's recent network requests.",
    "javascript_exec": "Run JavaScript in the page and return the result.",
    "new_tab": "Open a new tab.",
    "list_tabs": "List tabs.",
    "switch_tab": "Switch to the given tab.",
    "close_tab": "Close the given tab.",
}

TAB_ID = "Tab id; the current tab when omitted"
REF = "A ref returned by read_page or find, e.g. ref_2"
TARGET = "A coordinate or element ref"
MODIFIERS = "Modifier keys held down, e.g. shift, ctrl+shift"
URL = "A URL, or back, forward, reload"
SCROLL_AMOUNT = "Scroll amount, 1 to 10, default 3"
KEY_TEXT = "A single key (e.g. Enter), a key combination (e.g. ctrl+a), or a space-separated sequence of keys (e.g. Backspace Backspace)"
WAIT_DURATION = "Seconds to wait, 0 to 30"
READ_FILTER = "interactive returns only actionable elements; all returns every element"
READ_REF = "Read only the content inside this element"
FIND_QUERY = "Text to look for"
UPLOAD_PATHS = "Paths of files or folders on the node the browser runs on"
JAVASCRIPT = "JavaScript code to run in the page"

REQUESTS_BLOCKED = "URL rules blocked {count} requests; the page may be incomplete."
USER_ACTED = "Since the last action, the user has operated tab(s) {tabs}; the page may have changed."
DONE = "Done."

TAKEOVER_DESCRIPTION = "Ask the user to take over the browser. Call this when signing in, entering a password or verification code, confirming a payment, or when you hit something you can't complete yourself."
TAKEOVER_REASON = "What the user needs to do, and why"
TAKEOVER_DONE = "The user says they're done; the page may have changed."
TAKEOVER_NOT_DONE = "The user didn't complete the action{note}."
TAKEOVER_NOTE = " (user's note: {note})"

SCREENSHOT = "Screenshot ({width}x{height}):"
NAVIGATE_BLOCKED = "URL rules don't allow opening this URL or its redirect target: {urls}"
NAVIGATE_FAILED = "Failed to open: {error}"
OPENED = "Opened {url}"
ZOOM_REGION = "[x0, y0, x1, y1]: the rectangle to zoom into, from the top-left (x0, y0) to the bottom-right (x1, y1), in the same coordinate system as the screenshot"
ZOOM_EMPTY = "The region given to zoom is empty"
CLICKED_REF = "Clicked {ref}"
CLICKED_POINT = "Clicked that position"
HOVERED = "Hovered"
DRAGGED = "Dragged"
MOUSE_DOWN = "Left button pressed"
MOUSE_UP = "Left button released"
MOUSE_MOVED = "Mouse moved"
SCROLLED = "Scrolled"
SCROLLED_TO = "Scrolled to {ref}"
# Sensitive inputs: chosen depending on whether the session has browser_takeover
SENSITIVE_FOCUS_TAKEOVER = "The current focus is a password, bank card or verification code input. Call browser_takeover."
SENSITIVE_FOCUS_USER = "The current focus is a password, bank card or verification code input; the user must type it themselves."
SENSITIVE_FIELD_TAKEOVER = "This element is a password, bank card or verification code input. Call browser_takeover."
SENSITIVE_FIELD_USER = "This element is a password, bank card or verification code input; the user must type it themselves."
PAUSED = "Operations are paused on the device; the browser can't be used for now."
RECONNECTED = "The connection to the browser dropped and was re-established; previous tab ids are no longer valid."
TYPED = "Typed"
KEY_PRESSED = "Key pressed"
KEY_RELEASED = "Key released"
WAITED = "Wait finished"
PAGE = "Page: {title} — {url}\n{text}"
PAGE_EMPTY = "(no content)"
NOT_FOUND = "No matching elements found"
NO_TEXT = "(no text on the page)"
FIELD_SET = "Set {ref}"
UPLOADED = "Uploaded {count} file(s)"
NO_CONSOLE = "(no console logs)"
NO_NETWORK = "(no network requests recorded)"
SCRIPT_FAILED = "Execution failed: {error}"
TAB_OPENED = "Opened new tab {tab} and made it the current tab"
NO_TABS = "(no tabs)"
TAB_SWITCHED = "Switched to {tab}"
TAB_CLOSED = "Closed {tab}"

# The browser section of the environment description
FACTS_TITLE = "Browser"
FACTS_ITEM = "- {name}: {value}"
FACTS_SEPARATOR = ", "
FACTS_NODE = "Node"
FACTS_DIRS = "Directories"
FACTS_DESCRIPTION = "Description"

DOWNLOAD_COMPLETED = "Download complete: {name}, saved at {path}."
DOWNLOAD_COMPLETED_BY_BROWSER = "Download complete: {name}."
DOWNLOAD_FAILED = "Download failed: {name}: {error}"

UPLOAD_NO_NODE = "Can't upload files"
UPLOAD_NOT_ABSOLUTE = "{path} must be an absolute path on the node the browser runs on"
UPLOAD_NOT_FOUND = "{path} doesn't exist on the node the browser runs on"
UPLOAD_NOT_ALLOWED = "{path} is not in a location files may be uploaded from"
UPLOAD_SANDBOX = "Sandbox rules don't allow reading {path}"
UPLOAD_ONE_DIRECTORY = "Only one folder can be uploaded at a time, and not together with files"
UPLOAD_NO_DIRECTORY = "This upload input doesn't accept folders"
UPLOAD_SINGLE = "This upload input only accepts one file"
