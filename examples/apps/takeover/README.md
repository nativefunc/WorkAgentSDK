# User takeover

When the agent hits a sign-in, CAPTCHA or similar, it asks the user to take over. The user sees live frames of the browser or screen in a web page and operates it directly.

## Run

```bash
pip install fastapi "uvicorn[standard]" openai playwright
uvicorn app:app --port 8000
```

## API

| Endpoint | Description |
| :-- | :-- |
| `POST /sessions` | Create a session. With `computer=true`, the session also gets a computer |
| `POST /sessions/{id}/messages` | Send a message; returns any takeover requests awaiting an answer |
| `WS /sessions/{id}/takeover/{request_id}` | Takeover: pushes live frames and receives the user's actions |

Takeover WebSocket messages:

| Direction | Message |
| :-- | :-- |
| Backend to frontend | Binary messages, each one JPEG frame |
| Frontend to backend | `{"type": "input", "action": "left_click", "args": {...}}`, a user action |
| Frontend to backend | `{"type": "done"}`, the user is done and the turn continues |

Browser coordinates are page CSS pixels and computer coordinates are actual screen pixels; the frontend converts them using the frame size. For actions and arguments see [Browser](../../../docs/reference/browser.md#actions) and [Computer](../../../docs/reference/computer.md#actions).
