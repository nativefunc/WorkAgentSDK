# Nodes

| Example | Contents |
| :-- | :-- |
| [device_listen.py](device_listen.py) | Backend connects to a device; the agent runs commands in the device's workspace |

When the backend connects to the device, the device program listens on an address and the backend connects to it. Useful when the backend can reach the device, such as a server on an internal network.

## Run

1. Generate a token:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))" > ~/device-token
   export DEVICE_TOKEN=$(cat ~/device-token)
   ```

2. Start the device program on the device. This demo uses the local machine:

   ```bash
   python -m work_agent_sdk.cli device --name build-box \
       --listen 127.0.0.1:7000 --token-file ~/device-token \
       --workspace ~/device-workspace --sandbox srt
   ```

   For an encrypted connection, add `--tls-cert` and `--tls-key` to the device program and use a `wss://` address on the backend.

3. Run the example:

   ```bash
   python device_listen.py
   ```
