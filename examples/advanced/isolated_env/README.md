# Isolated environment

Start a Docker container for each session; the agent works inside the container, and the container is deleted when the session ends.

The example code starts and deletes the containers with the `docker` command; the SDK only connects to the device program inside the container.

## Run

1. Build the device program image from the source root:

   ```bash
   docker build -f docker/device/Dockerfile -t work-agent-device .
   ```

2. Run the example:

   ```bash
   python main.py
   ```

The device program in the container listens on port 7000, which is mapped to a random port on the local machine; the backend connects to that port. The backend and Docker must be on the same machine.

## Audit log

The device program records every operation the backend performs in the container. Logs are saved in `audit-logs/<container-name>` in the current directory and are kept after the container is deleted.
