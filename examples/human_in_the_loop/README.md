# Human in the loop

| Example | Contents |
| :-- | :-- |
| [approval.py](approval.py) | Issue a request and wait for the user to confirm |
| [requests.py](requests.py) | Custom requests: asking the user to choose, tools run by the frontend, requests answered by the backend, entering a password |
| [hooks.py](hooks.py) | Hooks: answer commands without the model, pick the model per user plan, block writes to production, audit and truncate tool results, make the model verify its changes, switch to a fallback model |

## Run

Run from this directory, e.g.:

```bash
python approval.py
```

`approval.py` and `requests.py` ask questions in the terminal and continue once you type an answer.
