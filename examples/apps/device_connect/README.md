# Device connects to the backend

The device program connects to the backend, and the agent runs commands in the device's workspace. Useful when the backend can't reach the device, such as a user's computer.

## Run

1. Start the backend:

   ```bash
   pip install fastapi "uvicorn[standard]" openai
   uvicorn backend:app --port 8000
   ```

2. Register the device and issue a token:

   ```bash
   curl -X POST "http://127.0.0.1:8000/devices?user=alice"
   ```

3. Run the device program on the device; `WORK_AGENT_DEVICE_TOKEN` is the token returned in the previous step:

   ```bash
   export WORK_AGENT_DEVICE_TOKEN=...
   python -m work_agent_sdk.cli device --name user-alice \
       --url ws://127.0.0.1:8000/work_agent_sdk/nodes \
       --workspace ~/agent-workspace --sandbox srt
   ```

4. Send a task:

   ```bash
   curl -X POST "http://127.0.0.1:8000/tasks?user=alice" -H "content-type: application/json" \
       -d '{"text": "Create notes.md in the workspace and write the current date in it"}'
   ```

## API

| Endpoint | Description |
| :-- | :-- |
| `WS /work_agent_sdk/nodes` | Address the device program connects to |
| `POST /devices` | Register a device and issue a token. Calling again issues a new token and the old one stops working |
| `GET /devices` | Return device status |
| `POST /tasks` | Run a task in the device's workspace and return the result |

Registrations made with `runner.nodes.add()` are not persisted. The example saves registered devices in `devices.json` and registers them again when the backend starts. Tokens are stored in the Runner's data directory and remain valid after the backend restarts.
