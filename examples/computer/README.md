# Computer

| Example | Contents |
| :-- | :-- |
| [computer.py](computer.py) | Operate desktop apps, handle app authorization and takeover requests |

The example operates this machine's screen. Before running it, the machine needs a graphical desktop and a text editor installed.

## Linux

Requires an X11 desktop; Wayland sessions are not supported. On systems that default to Wayland, such as Ubuntu, choose an X11 (Xorg) session on the login screen.

Install the dependencies:

```bash
sudo apt install xdotool x11-utils
pip install Pillow
```

| Dependency | Used for |
| :-- | :-- |
| `xdotool` | Moving the mouse, clicking, typing, switching windows |
| `x11-utils` | Provides `xprop` and `xwininfo` for identifying windows and apps |
| `Pillow` | Compressing and scaling screenshots |

Set the desktop with the `DISPLAY` environment variable; `:0` when unset.

### Machines without a monitor

Create a virtual desktop with Xvfb. Switching windows needs a window manager; this uses Openbox, with Mousepad as the text editor:

```bash
sudo apt install xvfb openbox mousepad
Xvfb :1 -screen 0 1280x800x24 &
DISPLAY=:1 openbox &
DISPLAY=:1 python computer.py
```

## macOS

Install the dependencies:

```bash
pip install Pillow pyautogui
```

In "System Settings → Privacy & Security", grant the terminal that runs the example the "Accessibility" and "Screen Recording" permissions, then reopen the terminal.

## Windows

Install the dependencies:

```bash
pip install Pillow pyautogui
```

## Run

```bash
python computer.py
```

When the agent requests to operate an app, type `y` in the terminal to allow it. When the agent asks you to take over, finish the task on the computer and press Enter.
