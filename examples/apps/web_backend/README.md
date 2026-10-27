# Web backend

Provides a chat API with FastAPI, pushes events over SSE, and approves refunds in a web page.

## Run

```bash
pip install fastapi uvicorn openai
uvicorn app:app --port 8000
```

Open http://127.0.0.1:8000 , send "Refund 99 yuan for order A1024", and approve or deny the refund in the page.

With the default storage only one process can run; don't set `--workers`.

## API

The example uses a `user` parameter instead of sign-in; every endpoint requires it.

| Endpoint | Description |
| :-- | :-- |
| `POST /sessions` | Create a session |
| `POST /sessions/{id}/messages` | Send a message |
| `GET /sessions/{id}/events` | Push the session's events over SSE |
| `POST /sessions/{id}/requests/{request_id}` | Answer a request |
| `POST /sessions/{id}/stop` | Stop the current turn |
| `POST /sessions/{id}/close` | Close the session |
