# Requests

```python
from work_agent_sdk import Approval, Request
```

## Request

```python
class Request(BaseModel, answered_by="user")
```

Base class for custom requests, passed to [`ctx.wait_for()`](tools.md#methods). The request's fields are what gets sent to the frontend; the inner class `Answer` defines the fields of the answer:

```python
class ChooseOption(Request):
    question: str
    options: list[str]

    class Answer(BaseModel):
        choice: str
```

When `Answer` is not defined, the answer can be any dict. When `Answer` has fields of type `SecretStr` or `SecretBytes`, the answer is not saved to storage.

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `answered_by` | `str` | `"user"` | Who answers. Values: `user` or `backend` |

## PendingRequest

Requests in `session.pending()` and `TurnResult.pending`.

| Field | Type | Description |
| :-- | :-- | :-- |
| `id` | `str` | Request ID |
| `type` | `str` | Name of the request class, e.g. `Approval` |
| `data` | `dict` | Fields of the request |
| `answer_schema` | `dict` | JSON Schema of the answer |
| `answered_by` | `str` | Who answers. Values: `user` or `backend` |
| `sensitive` | `bool` | Whether the answer contains `SecretStr` or `SecretBytes` fields |
| `session_id` | `str` | ID of the session that issued the request |
| `agent` | `str` | Name of the agent that issued the request |
| `call_id` | `str \| None` | ID of the tool call that issued the request |
| `created_at` | `float` | Time the request was issued |

## Built-in requests

| Request | Description |
| :-- | :-- |
| [`Approval`](#approval) | Ask the user to approve or deny |
| [`ClientTool`](#clienttool) | Ask the frontend to run a tool |
| [`Takeover`](browser.md#takeover) | Ask the user to take over the browser or computer |
| [`AppAccess`](computer.md#appaccess) | Request to operate apps on the computer |
| [`Authorization`](mcp.md#authorization) | Ask the user to authorize an MCP server |

### Approval

```python
Approval(*, title: str, detail: Any = None)
```

| Parameter | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `title` | `str` | Required | Title |
| `detail` | `Any` | `None` | Details shown to the user |

`Approval.Answer`:

| Field | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `approved` | `bool` | Required | Whether approved |
| `note` | `str` | `""` | Note |

### ClientTool

Request issued when a tool with `client=True` is called.

| Field | Type | Description |
| :-- | :-- | :-- |
| `tool` | `str` | Tool name |
| `args` | `dict` | Tool arguments |

The answer is the tool's result, in the format given by the tool's `output_schema`.

## Examples

- [human_in_the_loop/approval.py](../../examples/human_in_the_loop/approval.py): ask the user to confirm before deploying, using `ctx.step()`
- [human_in_the_loop/requests.py](../../examples/human_in_the_loop/requests.py): custom requests, tools run by the frontend, requests answered by the backend, sensitive answers
