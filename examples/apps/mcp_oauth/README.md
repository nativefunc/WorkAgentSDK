# MCP OAuth authorization

When an MCP server needs user authorization, show the authorization link in a web page. After the user authorizes, show the agent's answer.

## Run

```bash
pip install fastapi uvicorn openai mcp cryptography
export WORK_AGENT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
export TRACKER_MCP_URL=https://mcp.tracker.example.com/mcp
uvicorn app:app --port 8000
```

Open http://127.0.0.1:8000/ask?text=list+my+todos . If not yet authorized, the page shows an authorization link; after authorization it redirects to `/oauth/callback` and shows the answer.

With `WORK_AGENT_SECRET_KEY` set, tokens are encrypted and saved to storage, so no re-authorization is needed after the backend restarts. In this example all requests use the same session.

## API

| Endpoint | Description |
| :-- | :-- |
| `GET /ask` | Send a message. Returns an authorization link when authorization is needed |
| `GET /oauth/callback` | Authorization callback; returns the answer once authorization completes |
| `POST /oauth/revoke` | Revoke authorization |
