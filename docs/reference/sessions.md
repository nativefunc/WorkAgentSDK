# Sessions

## Session

Session returned by `runner.new_session()` and `runner.session()`.

### Attributes

| Name | Description |
| :-- | :-- |
| `id` | Session ID |
| `queue` | Message queue. See [SessionQueue](#sessionqueue) |

### Methods

| Method | Description |
| :-- | :-- |
| [`send(content, files, priority, metadata)`](#send) | Send a message |
| [`answer(request_id, value)`](#answer) | Answer a request |
| `pending()` | Return requests awaiting an answer in this session and its child sessions, each a [`PendingRequest`](requests.md#pendingrequest) |
| [`events(after, snapshot, children, live)`](#events) | Subscribe to events |
| `add_message(message)` | Add a [`CustomMessage`](#custommessage) and return it. The model sees the `for_model` content on its next answer |
| [`update_message(message_id, data, display)`](#update_message) | Update a `CustomMessage` |
| [`complete_message(message_id, status, data, for_model)`](#complete_message) | Finish an in-progress `CustomMessage` |
| [`history(view)`](#history) | Return the messages in the session |
| [`update(model, thinking)`](#update) | Switch the model or thinking level |
| [`stop(everything)`](#stop) | Stop the current turn |
| [`rewind(message_id)`](#rewind) | Retract a user message and everything after it |
| [`fork(message_id)`](#fork) | Fork the session |
| [`spawn(agent, prompt, report)`](#spawn) | Create a child session |
| `children()` | Return child sessions |
| `root()` | Return the top-level session |
| `info()` | Return [`SessionInfo`](#sessioninfo) |
| `usage()` | Return the cumulative usage of this session and its child sessions |
| [`trace(turn_id)`](#trace) | Return the execution trace |
| `resource(name)` | Return a resource |
| `workspace()`, `browser()`, `computer()` | Return the workspace, browser and computer. See [BoundWorkspace](workspace.md#boundworkspace), [BoundBrowser](browser.md#boundbrowser), [BoundComputer](computer.md#boundcomputer) |
| [`close(outcome)`](#close) | Close the session |
| `delete()` | Delete the session and its records |

### send()

```python
def send(
    content: str | UserMessage | CustomMessage,
    *,
    files: list[str] | None = None,
    priority: int = 0,
    metadata: dict | None = None,
) -> TurnHandle
```

Sends a message and returns a [`TurnHandle`](#turnhandle). A session handles one message at a time; messages received while the agent is answering wait in the queue and are handled in `priority` order. Raises `SessionClosed` if the session is closed.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `content` | `str \| UserMessage \| CustomMessage` | Required | Message content |
| `files` | `list[str] \| None` | `None` | Paths of attached files |
| `priority` | `int` | `0` | Priority in the queue; higher values are handled first |
| `metadata` | `dict \| None` | `None` | Extra data for this turn |

### answer()

```python
def answer(request_id: str, value: Any) -> TurnHandle
```

Answers a request in this session or its child sessions and returns a [`TurnHandle`](#turnhandle). See [Requests](requests.md).

| Parameter | Type | Description |
| :-- | :-- | :-- |
| `request_id` | `str` | Request ID |
| `value` | `Any` | The answer, in the format given by the request's `answer_schema` |

### events()

```python
async def events(*, after: int = 0, snapshot: bool = False, children: bool = False, live: bool = True) -> AsyncIterator[Event]
```

Subscribes to the session's [events](#session-events).

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `after` | `int` | `0` | Of the stored events, only return those with a sequence number greater than this. After a disconnect, pass the last `seq` received |
| `snapshot` | `bool` | `False` | Whether to first return the current content of in-progress messages |
| `children` | `bool` | `False` | Whether to include events from child sessions |
| `live` | `bool` | `True` | Whether to keep returning new events. When `False`, ends after returning stored events |

### update_message()

```python
async def update_message(message_id: str, *, data: Any = ..., display: bool = ...) -> None
```

Updates a `CustomMessage`. Parameters not passed are left unchanged.

| Parameter | Type | Description |
| :-- | :-- | :-- |
| `message_id` | `str` | Message ID |
| `data` | `Any` | New extra data |
| `display` | `bool` | Whether to show it to the user |

### complete_message()

```python
async def complete_message(
    message_id: str,
    *,
    status: str = "completed",
    data: Any = ...,
    for_model: str | None = ...,
) -> bool
```

Finishes a `CustomMessage` whose status is `in_progress`. Returns `False` if the message has already finished.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `message_id` | `str` | Required | Message ID |
| `status` | `str` | `"completed"` | Final status. Values: `completed`, `failed`, `cancelled` or `interrupted` |
| `data` | `Any` | Unchanged | New extra data |
| `for_model` | `str \| None` | Unchanged | Text the model sees |

### history()

```python
async def history(view: str = "raw") -> list[Message]
```

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `view` | `str` | `"raw"` | Values: `raw` (messages in the session) or `model` (messages sent to the model) |

### update()

```python
async def update(*, model: str | None = ..., thinking: str | None = ...) -> None
```

Switches the model or thinking level, effective from the next model call. Parameters not passed are left unchanged.

| Parameter | Type | Description |
| :-- | :-- | :-- |
| `model` | `str \| None` | Model ID; must be the agent's model or one of `Runner`'s `models`. `None` restores the agent's model |
| `thinking` | `str \| None` | Thinking level. Values: `off`, `low`, `medium`, `high` or `max`. `None` restores the agent's setting |

### stop()

```python
async def stop(*, everything: bool = False) -> None
```

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `everything` | `bool` | `False` | Whether to also stop child sessions and background processes |

### rewind()

```python
async def rewind(message_id: str) -> list[str]
```

Retracts the user message given by `message_id` and everything after it; returns the retracted message IDs. Top-level sessions only.

### fork()

```python
async def fork(message_id: str | None = None) -> Session
```

Forks the session and returns the new session. `message_id` is the ID of a user message; the new session contains only what came before it. Copies everything when unset. Top-level sessions only.

### spawn()

```python
async def spawn(agent: Agent | str, prompt: str | None = None, *, report: bool = True) -> Session
```

Creates a child session and returns it.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `agent` | `Agent \| str` | Required | Agent or agent name |
| `prompt` | `str \| None` | `None` | First message sent to the child session |
| `report` | `bool` | `True` | Whether to send the child session's result for each turn to the parent session |

### trace()

```python
async def trace(turn_id: str | None = None) -> list[dict]
```

Returns the execution trace. `turn_id` is the turn ID; returns the trace of all turns when unset.

### close()

```python
async def close(*, outcome: str = "closed") -> None
```

Closes the session and its child sessions. `outcome` is the reason for closing, stored in `SessionInfo.outcome`.

## SessionQueue

Methods of `session.queue`.

| Method | Description |
| :-- | :-- |
| `list()` | Return the [`QueueItem`](#queueitem)s in the queue, in processing order |
| `set_priority(item_id, priority)` | Change the priority; returns whether it succeeded |
| `cancel(item_id)` | Remove from the queue; returns whether it succeeded |

## TurnHandle

Return value of `send()` and `answer()`.

| Usage | Description |
| :-- | :-- |
| `await handle` | Wait for the turn to end; returns a [`TurnResult`](#turnresult) |
| `async for event in handle` | Yield the turn's events one by one, for streaming output |
| `await handle.queued()` | Return the [`QueueItem`](#queueitem) as soon as it is queued, without waiting for the turn to end |

## TurnResult

| Field | Type | Description |
| :-- | :-- | :-- |
| `turn_id` | `str` | Turn ID |
| `status` | `str` | Status; see the table below for values |
| `text` | `str` | The agent's answer |
| `data` | `Any` | Structured data. See `Agent`'s [`output`](agent.md#agent) |
| `pending` | `list[PendingRequest]` | Requests awaiting an answer. See [PendingRequest](requests.md#pendingrequest) |
| `error` | `ErrorInfo \| None` | Error information. See [ErrorInfo](#errorinfo) |
| `usage` | `Usage` | Usage of this `send()` or `answer()` |

| `status` | Description |
| :-- | :-- |
| `completed` | The agent gave an answer |
| `waiting` | Waiting for an answer to a request |
| `stopped` | Stopped by calling `stop()` |
| `error` | An error occurred; see `error` for the reason |
| `rejected` | Rejected by a hook. See [Hooks](hooks.md) |
| `cancelled` | A queued message was cancelled, or a new message arrived while waiting for an answer |

## ErrorInfo

| Field | Type | Description |
| :-- | :-- | :-- |
| `code` | `str` | Error code |
| `message` | `str` | Error description |
| `source` | `str` | Where the error occurred. Values: `model`, `tool`, `hook` or `internal` |
| `retryable` | `bool` | Whether it can be retried |
| `data` | `Any` | Extra data |

## SessionInfo

| Field | Type | Description |
| :-- | :-- | :-- |
| `id` | `str` | Session ID |
| `agent` | `str` | Agent name |
| `status` | `str` | Status. Values: `open` or `closed` |
| `activity` | `str` | Current activity. Values: `idle`, `running` or `waiting` |
| `queued` | `int` | Number of messages in the queue |
| `metadata` | `dict` | Extra data of the session |
| `outcome` | `str \| None` | Reason for closing |
| `model`, `thinking` | `str \| None` | Current model and thinking level |
| `resources` | `list[str]` | Resource names, e.g. `workspace` |
| `parent_id`, `root_id` | `str \| None`, `str` | IDs of the parent session and the top-level session |
| `created_at`, `updated_at` | `float` | Creation time and update time |

## CustomMessage

```python
from work_agent_sdk import CustomMessage
```

```python
CustomMessage(kind: str, data: Any = None, *, for_model: str | None = None, display: bool = True, status: str = "completed")
```

A custom message, such as a notification from an external system.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `kind` | `str` | Required | Message kind, e.g. `order_shipped` |
| `data` | `Any` | `None` | Extra data |
| `for_model` | `str \| None` | `None` | Text the model sees. When unset, the model doesn't see this message |
| `display` | `bool` | `True` | Whether to show it to the user |
| `status` | `str` | `"completed"` | Status. Values: `completed` or `in_progress`. Finish `in_progress` messages with `complete_message()` |

## QueueItem

| Field | Type | Description |
| :-- | :-- | :-- |
| `id` | `str` | ID |
| `message` | `UserMessage \| CustomMessage` | Message |
| `priority` | `int` | Priority |
| `metadata` | `dict` | The `metadata` passed to `send()` |
| `created_at` | `float` | Time it was queued |

## Session events

```python
from work_agent_sdk.events import MessageUpdated, TurnEnded
```

All events have the following fields:

| Field | Type | Description |
| :-- | :-- | :-- |
| `type` | `str` | Event type |
| `seq` | `int \| None` | Sequence number. Only stored events have one |
| `session_id` | `str \| None` | Session ID |
| `turn_id` | `str \| None` | Turn ID |
| `ts` | `float` | Time it occurred |

Use `event.to_dict()` to turn an event into a dict. Common events:

| Event | Description |
| :-- | :-- |
| `MessageStarted` | A message started. `message` is the message |
| `MessageUpdated` | A message was updated. `delta` is the new content; see the table below |
| `MessageCompleted` | A message completed. `message` is the full message |
| `RequestOpened` | A request was issued. `request` is the request |
| `TurnStarted` | A turn started. `source` is where the turn came from, e.g. `schedule` |
| `TurnEnded` | A turn ended. `result` is the [`TurnResult`](#turnresult) |

| `delta` | Description |
| :-- | :-- |
| `{"kind": "text", "text": ...}` | Answer text |
| `{"kind": "thinking", "text": ...}` | Thinking content |
| `{"kind": "tool_args", "name": ..., "text": ...}` | Tool call arguments |
| `{"progress": ...}` | Data pushed by a tool via `ctx.stream()` |

For node events see [Node events](nodes.md#node-events).

## Exceptions

```python
from work_agent_sdk import InvalidAnswer, RequestClosed, SessionClosed
```

| Exception | Description |
| :-- | :-- |
| `SessionClosed` | A message was sent or a request answered on a closed session |
| `InvalidAnswer` | The answer doesn't match the request's `answer_schema`; the request keeps waiting for an answer |
| `RequestClosed` | The request doesn't exist or is no longer awaiting an answer |

## Examples

- [basic/streaming.py](../../examples/basic/streaming.py): streaming output
- [sessions/event_stream.py](../../examples/sessions/event_stream.py): all events in a turn
- [sessions/reconnect.py](../../examples/sessions/reconnect.py): resubscribe after a disconnect using `after` and `snapshot`
- [sessions/sessions.py](../../examples/sessions/sessions.py): reopen a session, add messages, message queue, rewind, fork
- [apps/web_backend](../../examples/apps/web_backend): send messages, push events and answer requests from a web backend
- [apps/webhook](../../examples/apps/webhook): receive notifications from external systems with `CustomMessage`
