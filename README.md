# cli-paste

`cli-paste` is a Windows helper for terminal-first AI workflows.

When you press `Ctrl+V` or terminal right-click with an image in your clipboard, it saves the image to disk and pastes the saved file path instead. This is useful for tools such as Codex, Claude Code, and similar terminal apps that accept image paths but cannot read clipboard images directly.

## What it does

- Watches `Ctrl+V` and right-click in supported terminal windows
- Detects whether the clipboard currently contains an image
- Saves the image as a `.png` file
- Replaces the clipboard contents with that file path
- Simulates paste into the active terminal window

Non-terminal windows are left alone. Normal text paste keeps working.

## Requirements

- Windows 10 or Windows 11
- Python 3.8+
- An interactive desktop session

Runtime dependencies:

- `keyboard`
- `pywin32`
- `Pillow`

## Quick start

```powershell
git clone https://github.com/phenixnull/cli-paste.git
cd cli-paste
start.bat
```

`start.bat` does the following:

1. Starts `dist\cli_paste.exe` if you already built a packaged release.
2. Otherwise finds Python, creates `.venv`, installs dependencies, and launches the GUI.

## Manual setup

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python gui.py
```

## Configuration

Environment variables:

- `CLI_PASTE_PYTHON`: full path to `python.exe` if Python is not on `PATH`
- `CLI_PASTE_PYTHONW`: optional full path to `pythonw.exe` for background launches
- `CLI_PASTE_PIP_INDEX_URL`: optional custom package index URL for dependency installation

Runtime settings:

- Image cache directory can be changed from the GUI `Settings` dialog
- Default cache directory is `%USERPROFILE%\Pictures\CLI_temp`
- `Run at login` creates a Windows Task Scheduler entry for the background worker

### Custom cache path

`cli-paste` does not force a fixed paste cache directory.

- Default image cache path: `%USERPROFILE%\Pictures\CLI_temp`
- Open the GUI and click `Settings`
- Choose any writable folder you want to use for pasted images
- The chosen path is saved to `%APPDATA%\cli_paste\settings.json`
- If the background worker is already running, the GUI restarts it so the new cache path takes effect immediately

## Supported terminals

The terminal detector uses both process names and window classes. It is intended to work with:

- Windows Terminal
- PowerShell and `pwsh`
- CMD
- Git Bash and mintty
- WSL shells
- WezTerm
- Alacritty
- Tabby
- Hyper
- Terminus

## Project layout

```text
app_config.py    Shared config helpers and persisted settings
bootstrap.py     Creates/repairs the venv and launches the GUI
cli_paste.py     Low-level keyboard and mouse hooks, clipboard image handling
gui.py           Start/stop UI, cache settings, and startup task management
start.bat        Entry point for local use on Windows
```

## License

MIT
