# Browser

```python
from work_agent_sdk import Browser, BrowserPolicy, BrowserUse
```

## Browser

```python
Browser(
    *,
    node: str | None = None,
    cdp: str | None = None,
    profile: str = "session",
    policy: BrowserPolicy = BrowserPolicy.standard(),
    headless: bool | None = None,
    args: list[str] = [],
    executable: str | None = None,
    viewport: tuple[int, int] = (1280, 800),
    downloads: bool = True,
    download_dir: str | None = None,
    description: str = "",
)
```

The session's browser, passed as the `browser` argument of `runner.new_session()`. A session and its child sessions share one browser, each using its own tabs.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `node` | `str \| None` | `None` | Node that launches the browser. See [Nodes](nodes.md) |
| `cdp` | `str \| None` | `None` | CDP address of an already-running Chrome, e.g. `http://127.0.0.1:9222`. Chrome must be started with `--remote-debugging-port` |
| `profile` | `str` | `"session"` | Name of the user data, which holds cookies and sign-in state. `session` is per-session and deleted when the session closes; `shared` is the user data and tabs of the browser connected via `cdp`; any other name is shared by sessions using the same name |
| `policy` | `BrowserPolicy` | `BrowserPolicy.standard()` | Access rules. See [BrowserPolicy](#browserpolicy) |
| `headless` | `bool \| None` | `None` | Whether to hide the window. Hidden when unset |
| `args` | `list[str]` | `[]` | Browser launch arguments |
| `executable` | `str \| None` | `None` | Path to the browser executable |
| `viewport` | `tuple[int, int]` | `(1280, 800)` | Page width and height |
| `downloads` | `bool` | `True` | Whether downloads are allowed |
| `download_dir` | `str \| None` | `None` | Download directory. When unset, a temporary directory is used and deleted when the session closes |
| `description` | `str` | `""` | Description of the browser, sent to the model |

Set at least one of `node` and `cdp`.

## BrowserPolicy

```python
BrowserPolicy.standard(
    *,
    allow: bool | list[str] = True,
    deny: list[str] | None = None,
    private: bool | list[str] = False,
    enable: list[str] = (),
)
BrowserPolicy.open()
```

| Rule | `standard()` | `open()` |
| :-- | :-- | :-- |
| Public websites | Allowed. Adjust with `allow` and `deny` | Allowed |
| `localhost` and private network addresses | Blocked. Allow with `private` | Allowed |
| Sensitive inputs such as password fields | Typing blocked | Typing allowed |
| [Optional actions](#optional-actions) | Off. Enable with `enable`; the user confirms before each run | All enabled, no confirmation |

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `allow` | `bool \| list[str]` | `True` | Sites that may be visited. `True` means all public sites |
| `deny` | `list[str] \| None` | `None` | Sites that may not be visited |
| `private` | `bool \| list[str]` | `False` | `localhost` and private network addresses that may be visited, e.g. `["127.0.0.1:*"]`. `True` means all |
| `enable` | `list[str]` | `()` | Optional actions to enable |

Sites support the `*` wildcard. `*.example.com` matches subdomains but not `example.com`.

### Optional actions

| Action | Description |
| :-- | :-- |
| `file_upload` | Upload files |
| `read_console` | Read console logs |
| `read_network` | Read network requests |
| `javascript_exec` | Run JavaScript in the page |

## BrowserUse

```python
BrowserUse(*, takeover: bool = True)
```

Toolset that lets the agent operate the browser.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `takeover` | `bool` | `True` | Whether the model may ask the user to take over |

| Tool | Description |
| :-- | :-- |
| `browser_<action>` | Perform an [action](#actions), e.g. `browser_navigate` |
| `browser_takeover` | Ask the user to take over when something can't be completed, such as a sign-in or CAPTCHA; the session issues a [`Takeover`](#takeover) request |

### Actions

| Action | Parameters | Description |
| :-- | :-- | :-- |
| `navigate` | `url` | Open a URL |
| `screenshot` | | Take a screenshot |
| `zoom` | `region` | Zoom into a region of the screenshot; `region` is `[x1, y1, x2, y2]` |
| `left_click`, `right_click`, `middle_click`, `double_click`, `triple_click` | `target`, `modifiers` | Click |
| `hover` | `target` | Move the mouse over an element |
| `mouse_move`, `left_mouse_down`, `left_mouse_up` | `target` | Move the mouse, press or release the left button |
| `left_click_drag` | `from`, `target` | Drag |
| `scroll` | `target`, `scroll_direction`, `scroll_amount` | Scroll |
| `scroll_to` | `target` | Scroll to an element |
| `type` | `text` | Type text |
| `key` | `text`, `repeat` | Press keys, e.g. `ctrl+a` |
| `hold_key` | `text`, `duration` | Hold keys down |
| `form_input` | `target`, `value` | Fill in a form field |
| `read_page` | `filter`, `depth`, `ref` | Read the page structure |
| `find` | `query` | Find elements |
| `get_page_text` | | Read the page text |
| `wait` | `duration` | Wait (seconds) |
| `new_tab`, `list_tabs` | | Open a new tab, list tabs |
| `switch_tab`, `close_tab` | `tab_id` | Switch tab, close tab |
| `file_upload` | `target`, `paths` | Upload files. Optional action |
| `read_console`, `read_network` | | Read console logs, network requests. Optional actions |
| `javascript_exec` | `text` | Run JavaScript. Optional action |

All actions except the tab actions accept `tab_id` to target a specific tab.

`target` is either a coordinate `{"type": "coordinate", "x": 100, "y": 200}` or an element returned by `read_page` or `find`, `{"type": "ref", "ref": "ref_1"}`. `from` and `mouse_move` accept only coordinates; `scroll_to`, `form_input` and `file_upload` accept only elements.

## BoundBrowser

The browser returned by `session.browser()` and `ctx.browser`.

| Attribute | Type | Description |
| :-- | :-- | :-- |
| `policy` | `BrowserPolicy` | Access rules |
| `node` | `str \| None` | Node the browser runs on |
| `description` | `str` | Description of the browser |

| Method | Description |
| :-- | :-- |
| `perform(action, args)` | Perform an [action](#actions) and return a dict with the result, e.g. `perform("navigate", {"url": ...})`. Raises `PermissionError` when a site rule is violated; does not check whether optional actions are enabled |
| `screenshot(tab_id=None)` | Return a screenshot (JPEG). Uses the current tab when `tab_id` is not set |
| `viewport(tab_id=None)` | Return the page width and height |
| `watch(max_size=(1280, 800), quality=60, max_fps=5)` | Yield live frames, each a [`BrowserFrame`](#browserframe). Used to show the browser in a frontend |
| `user_input(action, args)` | Perform an action the user took in the frontend; coordinates are page CSS pixels. Supports `left_click`, `double_click`, `right_click`, `type`, `key`, `scroll`, `navigate`, `mouse_move` and `switch_tab` |
| `paused()` | Return whether the device owner has paused operations. See [Device status](nodes.md#device-status) |

## BrowserFrame

| Field | Type | Description |
| :-- | :-- | :-- |
| `image` | `bytes` | Frame (JPEG) |
| `width`, `height` | `int` | Frame width and height |
| `viewport_width`, `viewport_height` | `int` | Page width and height (CSS pixels) |
| `tab_id` | `str` | Tab ID |
| `url` | `str` | Page URL |
| `title` | `str` | Page title |

## Takeover

A request asking the user to take over the browser or computer. When the user is done, answer `{"done": True}`.

| Field | Type | Description |
| :-- | :-- | :-- |
| `reason` | `str` | Why the user needs to step in |
| `target` | `str` | What to take over. Values: `browser` or `computer` |
| `node` | `str \| None` | Node the browser or computer is on |
| `tab_id` | `str \| None` | Tab ID |
| `url` | `str \| None` | Page URL |

`Takeover.Answer`:

| Field | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `done` | `bool` | `True` | Whether the user has finished |
| `note` | `str` | `""` | Note |

## Examples

- [browser/browser.py](../../examples/browser/browser.py): launch a browser, set access rules, read pages from code
- [browser/cdp.py](../../examples/browser/cdp.py): connect to a running Chrome
- [apps/takeover](../../examples/apps/takeover): show the browser or screen in a web page and let the user take over
