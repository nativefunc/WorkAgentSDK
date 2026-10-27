# Custom service

Write a custom service that provides a SQLite database to sessions.

| Part | Description |
| :-- | :-- |
| `Database` | Resource configuration, passed when creating a session |
| `DatabaseService` | Opens and closes the database, tells the model which tables it has, checks inventory in the background and notifies the session |
| `SQL` | Toolset for querying and modifying the database |

## Run

```bash
python main.py
```

Prints two answers: the result of the inventory query, and the restocking suggestion given after receiving the low-stock notification.
