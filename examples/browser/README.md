# Browser

| Example | Contents |
| :-- | :-- |
| [browser.py](browser.py) | Access rules, keeping sign-in state, operating the browser from code |
| [cdp.py](cdp.py) | Connect to a running Chrome and use its sign-in state |

## Setup

Install Playwright and Chromium. If Chrome or Edge is already installed on this machine, you can skip the second command:

```bash
pip install playwright
playwright install chromium
```

Before running `cdp.py`, close all Chrome windows, start Chrome with a debugging port, and sign in to the sites you need:

| OS | Command |
| :-- | :-- |
| macOS | `/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222` |
| Linux | `google-chrome --remote-debugging-port=9222` |
| Windows | `"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222` |

## Run

Run from this directory, e.g.:

```bash
python browser.py
```
