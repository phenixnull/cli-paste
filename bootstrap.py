"""Bootstrap launcher for cli_paste."""

import os
import shutil
import subprocess
import sys
from datetime import datetime

from app_config import get_preferred_python, get_runtime_app_dir, is_venv_healthy

APP_DIR = get_runtime_app_dir()
VENV_DIR = os.path.join(APP_DIR, ".venv")
VENV_PYTHON = os.path.join(VENV_DIR, "Scripts", "python.exe")
VENV_PYTHONW = os.path.join(VENV_DIR, "Scripts", "pythonw.exe")
GUI_SCRIPT = os.path.join(APP_DIR, "gui.py")
REQUIREMENTS_FILE = os.path.join(APP_DIR, "requirements.txt")
LOG_FILE = os.path.join(APP_DIR, "cli_paste.log")
WORKER_ARG = "--worker"
PIP_INDEX_URL_ENV_VAR = "CLI_PASTE_PIP_INDEX_URL"
CREATE_NO_WINDOW = 0x08000000


def _append_log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[bootstrap {timestamp}] {message}\n")


def _run_checked(cmd):
    _append_log(f"run: {subprocess.list2cmdline(cmd)}")
    subprocess.run(cmd, cwd=APP_DIR, check=True)


def _rebuild_venv(base_python):
    if os.path.isdir(VENV_DIR):
        shutil.rmtree(VENV_DIR)

    _run_checked([base_python, "-m", "venv", VENV_DIR])
    pip_cmd = [VENV_PYTHON, "-m", "pip", "install", "-r", REQUIREMENTS_FILE]
    pip_index_url = os.environ.get(PIP_INDEX_URL_ENV_VAR, "").strip()
    if pip_index_url:
        pip_cmd.extend(["-i", pip_index_url])
    _run_checked(pip_cmd)


def _ensure_venv():
    base_python = get_preferred_python(windowless=False)
    if is_venv_healthy(VENV_DIR, preferred_python=base_python):
        return

    _append_log(f"rebuild venv with base python: {base_python}")
    _rebuild_venv(base_python)

    if not is_venv_healthy(VENV_DIR, preferred_python=base_python):
        raise RuntimeError(f"venv still invalid after rebuild: {VENV_DIR}")


def _get_launch_command(worker_mode):
    python_exe = VENV_PYTHONW if os.path.exists(VENV_PYTHONW) else VENV_PYTHON
    command = [python_exe, GUI_SCRIPT]
    if worker_mode:
        command.append(WORKER_ARG)
    return command


def _launch(worker_mode):
    cmd = _get_launch_command(worker_mode)
    creationflags = 0 if cmd[0].lower().endswith("pythonw.exe") else CREATE_NO_WINDOW
    _append_log(f"launch: {subprocess.list2cmdline(cmd)}")
    subprocess.Popen(cmd, cwd=APP_DIR, creationflags=creationflags)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    worker_mode = WORKER_ARG in args

    try:
        _ensure_venv()
        _launch(worker_mode)
        return 0
    except Exception as exc:
        _append_log(f"failed: {exc!r}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
