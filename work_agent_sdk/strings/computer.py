from __future__ import annotations

# Descriptions of app access tiers, shown to the user in access requests
TIER_WARNINGS = {
    "click": "Click and scroll only, no typing",
    "view": "View only",
}

ACTIONS = {
    "screenshot": "Take a screenshot of the screen.",
    "zoom": "Zoom in on a region of the screen.",
    "left_click": "Left-click.",
    "right_click": "Right-click.",
    "middle_click": "Middle-click.",
    "double_click": "Double-click.",
    "triple_click": "Triple-click (select a whole line).",
    "left_click_drag": "Hold the left button and drag from start_coordinate to coordinate.",
    "mouse_move": "Move the mouse.",
    "left_mouse_down": "Press the left button (without releasing).",
    "left_mouse_up": "Release the left button.",
    "cursor_position": "Get the current mouse position.",
    "scroll": "Scroll.",
    "type": "Type text.",
    "key": "Press a key or key combination.",
    "hold_key": "Hold a key down for a period of time.",
    "wait": "Wait for a period of time.",
}
MODIFIERS = "Modifier keys held down: shift, ctrl, alt, super, or joined with +, e.g. ctrl+shift"
COORDINATE = "[x, y] in screenshot pixels; clicks at the current mouse position when omitted"
ZOOM_REGION = "[x0, y0, x1, y1]: the rectangle to zoom into, from the top-left (x0, y0) to the bottom-right (x1, y1), in the same coordinate system as the screenshot"
SCROLL_AMOUNT = "Number of scroll wheel notches"
TYPE_TEXT = "Text to type"
KEY_TEXT = "A key or key combination, e.g. Return, ctrl+s, alt+Tab"
KEY_REPEAT = "Number of repetitions, 1 to 100"
DURATION = "Seconds, at most 300"

BATCH_DESCRIPTION = "Perform a sequence of computer actions in order and return a screenshot afterwards."
TAKEOVER_DESCRIPTION = "Ask the user to take over the computer. Call this when a password or verification code is needed, or when you hit something you can't complete yourself."
REQUEST_ACCESS_DESCRIPTION = (
    "Request to operate apps on the computer; once the user approves, the grant lasts for the current session. Operating unauthorized apps is refused, so request access with this tool first."
)
LIST_APPS_DESCRIPTION = "List authorized apps and their access tiers, running apps, and the current foreground app."
OPEN_APP_DESCRIPTION = "Open an app; if it's already running, bring it to the front. Returns a screenshot when done."

ACCESS_APPS = 'Names of the apps to operate, e.g. ["Microsoft Word"]; installed apps that aren\'t running can also be requested'
ACCESS_REASON = "Explain to the user why you need to operate these apps"
ACCESS_SYSTEM_KEYS = "Whether system shortcuts (e.g. switching or quitting apps) are also needed"
TAKEOVER_REASON = "What the user needs to do, and why"
OPEN_APP_APP = "App name or identity, e.g. Microsoft Word, com.apple.TextEdit"

CURSOR_POSITION = "Mouse position: ({x}, {y})"
DONE = "Done"
SCREENSHOT = "Screenshot ({width}x{height}):"
WAITED_FOR = "(The computer was in use by another task and this ran only after it was released; the screen may differ from what you last saw)"
USER_ACTED = "(Since the last action, the user has operated this computer; the screen may differ from what you last saw)"
BUSY = "The computer is in use by another task and still wasn't released after {seconds} seconds; try again later, or do other work first"
TAKEOVER_DONE = "The user says they're done; the screen may have changed."
TAKEOVER_NOT_DONE = "The user didn't complete the action{note}."
TAKEOVER_NOTE = " (user's note: {note})"
APP_OPENED = "{app} is in the foreground. Screenshot:"

ACCESS_REFUSED = "Not allowed to operate: {apps}"
ACCESS_MISSING = "Apps not found: {apps} (neither running nor installed)"
ACCESS_ALREADY_GRANTED = "The other apps can already be operated"
ACCESS_NOTHING = "No apps need to be requested"
ACCESS_DENIED = "The user declined{note}"
ACCESS_GRANTED = "The user approved: {granted}"
SYSTEM_KEYS = "System shortcuts"

APPS_AUTHORIZED = "Authorized apps: {apps}"
APPS_SYSTEM_KEYS = "System shortcuts: authorized"
APPS_RUNNING = "Running apps: {apps}"
APPS_FRONTMOST = "Foreground app: {app}"

# How authorized apps are written: fully operable apps list only the name; restricted ones note their tier
TIERS = {"click": "click and scroll only", "view": "view only"}
APP_WITH_TIER = "{app} ({tier})"
NONE = "None"

# The computer section of the environment description
FACTS_TITLE = "Computer"
FACTS_ITEM = "- {name}: {value}"
FACTS_SEPARATOR = ", "
FACTS_NODE = "Node"
FACTS_AUTHORIZED = "Authorized apps"
FACTS_LIMIT = "Access cap"
FACTS_LIMIT_VALUE = "{tier} (set on the device)"
FACTS_SHARED_FOLDER = "Shared folder"
FACTS_SHARED_FOLDER_VALUE = "{name} → {path}"
FACTS_DESCRIPTION = "Description"
