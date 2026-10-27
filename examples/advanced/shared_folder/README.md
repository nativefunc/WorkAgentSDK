# Shared folder

Workspace, browser and computer each run on a different machine and exchange files through a shared folder.

The agent downloads sales details from the reporting system, summarizes them into a spreadsheet in the workspace, opens the spreadsheet on the user's computer, then uploads it to the reporting system.

## Machines

The same NAS directory is mounted on three machines at different paths:

| Machine | Path | Used for |
| :-- | :-- | :-- |
| `dev-server` | `/mnt/team` | Workspace |
| `browser-host` | `/data/team` | Browser |
| `office-pc` | `/Volumes/team` | The user's Mac, for opening the spreadsheet |

Mounting and syncing are handled by ops. `SharedFolder` declares the path of this directory on each machine.

## Run

1. Install srt on `dev-server` and Playwright on `browser-host`.

2. Run the device program on all three machines, exposing the shared directory with `--workspace`:

   ```bash
   # dev-server
   python -m work_agent_sdk.cli device --name dev-server --listen 0.0.0.0:7443 \
       --token-file token --workspace ~/analysis --workspace /mnt/team --sandbox srt

   # browser-host
   python -m work_agent_sdk.cli device --name browser-host --listen 0.0.0.0:7443 \
       --token-file token --workspace /data/team --browser

   # office-pc
   python -m work_agent_sdk.cli device --name office-pc --listen 0.0.0.0:7443 \
       --token-file token --workspace /Volumes/team --screen
   ```

3. Set the three devices' tokens on the backend and run the example:

   ```bash
   export DEV_SERVER_TOKEN=... BROWSER_HOST_TOKEN=... OFFICE_PC_TOKEN=...
   python main.py
   ```

Before the browser uploads files and before the agent operates Numbers, the example asks the user to confirm in the terminal.
