# Receiving notifications from external systems

Add notifications from external systems to a session. This example uses build notifications from a CI system, with one session per repository.

| Notification | Handling |
| :-- | :-- |
| Build started | Add an in-progress message with `add_message()` |
| Build in progress | Update the progress with `update_message()` |
| Build succeeded | Finish the message with `complete_message()`; the agent sees the result on its next answer |
| Build failed | Finish the message and send a notification with `send()`; the agent analyzes why it failed |

## Run

```bash
pip install fastapi uvicorn openai
export CI_WEBHOOK_SECRET=...
uvicorn app:app --port 8000
```

Send a build failure notification:

```bash
body='{"repo": "acme/shop", "build_id": "123", "state": "failed", "log": "test_login FAILED"}'
sig=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$CI_WEBHOOK_SECRET" | cut -d' ' -f2)
curl -X POST http://127.0.0.1:8000/webhooks/ci -H "x-signature: $sig" -d "$body"
```
