# Computer

```python
from work_agent_sdk import Computer, ComputerPolicy, ComputerUse
```

## Computer

```python
Computer(*, node: str = "local", policy: ComputerPolicy = ComputerPolicy.standard(), display: str | None = None, description: str = "")
```

The session's computer, passed as the `computer` argument of `runner.new_session()`.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `node` | `str` | `"local"` | Node the computer is on. See [Nodes](nodes.md) |
| `policy` | `ComputerPolicy` | `ComputerPolicy.standard()` | Operation rules. See [ComputerPolicy](#computerpolicy) |
| `display` | `str \| None` | `None` | Linux X display number, e.g. `":1"` |
| `description` | `str` | `""` | Description of the computer, sent to the model |

## ComputerPolicy

```python
ComputerPolicy.standard(
    allow: list[str] | dict[str, str] | None = None,
    *,
    deny: list[str] | None = None,
    tiers: dict[str, list[str]] | None = None,
    system_keys: str = "ask",
    hold: str = "session",
)
ComputerPolicy.open(*, hold: str = "turn")
```

| Rule | `standard()` | `open()` |
| :-- | :-- | :-- |
| Operating apps | Requires user authorization; when the agent requests it, the session issues an [`AppAccess`](#appaccess) request. Apps in `allow` are pre-authorized | All apps may be operated |
| Access tier | Per app, see the table below | `full` for all apps |
| Password managers and keychains | Blocked | Allowed |
| System shortcuts | Per `system_keys` | Allowed |
| Holding the screen | Per `hold`; by default until the session closes | Per `hold`; by default released at the end of each turn |

| Access tier | What the agent can do |
| :-- | :-- |
| `full` | Click, type and press keys |
| `click` | Click and scroll |
| `view` | View only |

By default, browsers and trading apps are `view`, terminals and code editors are `click`, and other apps are `full`.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `allow` | `list[str] \| dict[str, str] \| None` | `None` | Pre-authorized apps. A list, or a dict from app name to access tier, e.g. `{"TextEdit": "full"}`. Names support the `*` wildcard |
| `deny` | `list[str] \| None` | `None` | Apps that may not be operated, appended to the default list |
| `tiers` | `dict[str, list[str]] \| None` | `None` | Apps for each access tier, replacing the default tiers, e.g. `{"view": ["*chrome*"]}` |
| `system_keys` | `str` | `"ask"` | Whether system shortcuts may be used. Values: `ask` (user approves on request), `allow` or `deny` |
| `hold` | `str` | `"session"` | How long the screen is held. Values: `session` (until the session closes) or `turn` (released at the end of each turn). While held, other sessions' actions wait |

System shortcuts are key combinations containing Win or Cmd, combinations containing `Ctrl+Alt`, plus `Alt+Tab` and `Alt+F4`.

## ComputerUse

```python
ComputerUse(*, max_size: tuple[int, int] = (1280, 800), screenshot_after_action: bool = True, takeover: bool = True)
```

Toolset that lets the agent operate the computer.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `max_size` | `tuple[int, int]` | `(1280, 800)` | Maximum width and height of screenshots sent to the model |
| `screenshot_after_action` | `bool` | `True` | Whether to return a screenshot after each action |
| `takeover` | `bool` | `True` | Whether the model may ask the user to take over |

| Tool | Description |
| :-- | :-- |
| `computer_<action>` | Perform an [action](#actions), e.g. `computer_left_click` |
| `computer_actions` | Perform a batch of actions. Replaces `computer_<action>` when an OpenAI model sets `native_tools=("computer",)` |
| `computer_open_app` | Open an app |
| `computer_list_apps` | List apps. Only provided in `standard()` |
| `computer_request_access` | Request authorization. Only provided in `standard()` |
| `computer_takeover` | Ask the user to take over; the session issues a [`Takeover`](browser.md#takeover) request with `target` set to `computer` |

### Actions

| Action | Parameters | Description |
| :-- | :-- | :-- |
| `screenshot` | | Take a screenshot |
| `zoom` | `region` | Zoom into a region of the screenshot; `region` is `[x1, y1, x2, y2]` |
| `left_click`, `right_click`, `middle_click`, `double_click`, `triple_click` | `coordinate`, `text` | Click. `text` holds modifier keys pressed at the same time, e.g. `shift` |
| `mouse_move` | `coordinate` | Move the mouse |
| `cursor_position` | | Return the mouse position |
| `left_click_drag` | `start_coordinate`, `coordinate` | Drag |
| `left_mouse_down`, `left_mouse_up` | | Press or release the left button |
| `scroll` | `scroll_direction`, `scroll_amount`, `coordinate` | Scroll. `scroll_direction` values: `up`, `down`, `left` or `right` |
| `type` | `text` | Type text |
| `key` | `text`, `repeat` | Press keys, e.g. `ctrl+s` |
| `hold_key` | `text`, `duration` | Hold keys down |
| `wait` | `duration` | Wait (seconds) |

Coordinates are `[x, y]`. Coordinates from the model are relative to the screenshot; coordinates passed to `act()` are screen pixels.

## BoundComputer

The computer returned by `session.computer()` and `ctx.computer`.

| Attribute | Type | Description |
| :-- | :-- | :-- |
| `policy` | `ComputerPolicy` | Operation rules |
| `description` | `str` | Description of the computer |
| `files` | `ScopedFiles` | Files on the machine the computer runs on. See [ScopedFiles](workspace.md#scopedfiles) |

| Method | Description |
| :-- | :-- |
| `screenshot(max_size=None, region=None)` | Return a screenshot (JPEG) and its width and height. `region` is the area to capture, in screen pixels |
| `size()` | Return the screen width and height |
| `act(action, args)` | Perform an [action](#actions); coordinates are screen pixels. Raises `PermissionError` when an operation rule is violated |
| `apps(installed=False)` | Return running apps. Includes installed apps when `installed=True` |
| `frontmost()` | Return the frontmost app |
| `open_app(app)` | Open an app, or bring it to the front |
| `watch(max_fps=2, max_size=(1280, 800))` | Yield live frames, each a [`ComputerFrame`](#computerframe). Used to show the screen in a frontend |
| `user_input(action, args)` | Perform an action the user took in the frontend; coordinates are screen pixels. Not subject to operation rules |
| `take_control(timeout=60)` | The user takes over the screen; the agent's actions wait meanwhile. `timeout` is how long the takeover lasts (seconds); `None` never expires. Returns [`ControlState`](#controlstate) |
| `keep_control()` | Extend the takeover; returns whether it is still active |
| `release_control()` | End the takeover |
| `control()` | Return the `ControlState` |
| `grants()` | Return the authorized apps |

## ComputerFrame

| Field | Type | Description |
| :-- | :-- | :-- |
| `image` | `bytes` | Frame (JPEG) |
| `width`, `height` | `int` | Frame width and height |
| `real_width`, `real_height` | `int` | Screen width and height (pixels) |

## ControlState

| Field | Type | Description |
| :-- | :-- | :-- |
| `by_user` | `bool` | Whether the user has taken over |
| `expires_at` | `float \| None` | When the takeover expires. `None` if it never expires or there is no takeover |
| `session_id` | `str \| None` | ID of the session holding the screen |

## AppAccess

Request issued when the agent asks to operate apps.

| Field | Type | Description |
| :-- | :-- | :-- |
| `reason` | `str` | Reason for the request |
| `apps` | `list[dict]` | Requested apps; each item has `id`, `name`, `exe`, `tier` and `warning` |
| `system_keys` | `bool` | Whether system shortcuts are requested |

`AppAccess.Answer`:

| Field | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `approved` | `bool` | Required | Whether approved. Once approved, the grant applies to the session and its child sessions until the session is deleted |
| `note` | `str` | `""` | Note |

## Examples

- [computer/computer.py](../../examples/computer/computer.py): operate apps on the computer, handle app authorization and takeover
- [apps/takeover](../../examples/apps/takeover): show the screen in a web page and let the user take over
