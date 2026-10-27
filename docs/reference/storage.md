# Storage

```python
from work_agent_sdk.store import KeyProvider, Store
```

## Data locations

SQLite is used by default, stored in `Runner`'s `data_dir`.

| Data | Location | To replace the storage |
| :-- | :-- | :-- |
| Sessions, events and message queue | `data_dir/work-agent.db` | `Runner(store=...)`, see [Store](#store) |
| Device tokens | `data_dir/nodes/nodes.db` | `Runner(device_tokens=...)` |
| Workspace process records | `data_dir/ext/workspace/workspace.db` | `Runner(services=[WorkspaceService(process_store=...)])` |
| Computer app grants and takeover state | `data_dir/ext/computer/computer.db` | `Runner(services=[ComputerService(store=...)])` |
| Scheduled tasks | `data_dir/ext/schedules/schedules.db` | `Runner(services=[ScheduleService(store=...)])` |
| MCP tokens | `data_dir/ext/mcp/mcp.db`, only saved when `secret_key` is set | `Runner(services=[MCPService(token_store=...)])` |

## Store

Storage interface for sessions, events and the message queue. The default implementation is `LocalStore(data_dir)`, using SQLite. To use another database, subclass `Store`, implement the methods below, and pass it to `Runner`'s `store` parameter.

| Method | Description |
| :-- | :-- |
| `open()` | Open the storage. Called when the Runner starts |
| `close()` | Close the storage. Called when the Runner shuts down |
| `create_session(record)` | Save a new session |
| `get_session(session_id)` | Return a session. Returns `None` if it doesn't exist |
| `update_session(record)` | Update a session |
| `delete_session(session_id)` | Delete a session with its events and queue |
| `list_sessions(agent=None, parent_id=None, root_id=None, status=None, top_level=False)` | List sessions matching the conditions |
| `append_event(session_id, event)` | Save an event and return its sequence number. Sequence numbers start at 1 and increase within each session |
| `events(session_id, after=0, types=None)` | Return events with a sequence number greater than `after`. `types` is a set of event types |
| `enqueue(item)` | Add a [`QueueItem`](sessions.md#queueitem) to the queue |
| `dequeue(item_id)` | Remove from the queue; returns whether it succeeded |
| `queued(session_id)` | Return the session's queue in processing order |
| `set_priority(item_id, priority)` | Change the priority; returns whether it succeeded |
| `clear_queue(session_id)` | Clear the session's queue; returns the removed items |

## Other storage interfaces

| Interface | Methods | Default implementation |
| :-- | :-- | :-- |
| `DeviceTokens` | `get(name)`, `put(name, digest)`, `delete(name)`, `names()`, `close()` | `SqliteDeviceTokens` |
| `ProcessStore` | `get(process_id)`, `put(record)`, `list(session_id=None, status=None)`, `delete(process_id)`, `close()` | `SqliteProcessStore` |
| `ComputerStore` | `get_grants(root_id)`, `put_grants(root_id, grants)`, `delete_grants(root_id)`, `get_takeover(screen)`, `put_takeover(screen, timeout)`, `delete_takeover(screen)`, `close()` | `SqliteComputerStore` |
| `ScheduleStore` | `get(job_id)`, `put(record)`, `list(session_id=None)`, `delete(job_id)`, `close()` | `SqliteScheduleStore` |
| `MCPTokenStore` | `get(name)`, `put(name, data)`, `delete(name)`, `close()` | `SqliteMCPTokenStore` |

`DeviceTokens` stores token digests; `MCPTokenStore` stores encrypted tokens.

## KeyProvider

Interface for encrypting MCP tokens. To use a key management service, subclass `KeyProvider`, implement the methods below, and pass it to `Runner`'s `secret_key`.

| Method | Description |
| :-- | :-- |
| `encrypt(data)` | Encrypt `bytes`, returning `bytes` |
| `decrypt(data)` | Decrypt `bytes`, returning `bytes` |
