from __future__ import annotations

import contextlib
import datetime
import json
import logging
import os
import threading
from typing import Any

DEFAULT_MAX_BYTES = 50 * 1024 * 1024
logger = logging.getLogger("work_agent_sdk.node")


class AuditLog:
    def __init__(self, path: str, *, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.path = os.path.abspath(os.path.expanduser(path))
        self.max_bytes = max_bytes

        # The Esc emergency stop fires on another thread and is logged as well
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._fd = self._open()

    def __repr__(self) -> str:
        return f"AuditLog({self.path!r})"

    def _open(self) -> int:
        return os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)

    def write(self, event: str, **fields: Any) -> None:
        record = {
            "ts": datetime.datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "event": event,
        }
        record.update({key: value for key, value in fields.items() if value is not None})
        line = (json.dumps(record, ensure_ascii=False, default=str) + "\n").encode()
        with self._lock:
            try:
                if os.fstat(self._fd).st_size + len(line) > self.max_bytes:
                    os.close(self._fd)
                    os.replace(self.path, self.path + ".1")
                    self._fd = self._open()
                os.write(self._fd, line)
            except OSError:
                # A failure to write the audit log (e.g. disk full) doesn't stop the device from working, but the device owner must be told
                logger.exception("Failed to write audit log: %s", self.path)

    def close(self) -> None:
        with self._lock, contextlib.suppress(OSError):
            os.close(self._fd)
