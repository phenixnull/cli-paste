"""Shared configuration helpers for cli_paste."""

import json
import os
import shutil
import sys

APP_NAME = "cli_paste"
SETTINGS_FILE = "settings.json"
DEFAULT_CACHE_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "CLI_temp")
PYTHON_ENV_VAR = "CLI_PASTE_PYTHON"
PYTHONW_ENV_VAR = "CLI_PASTE_PYTHONW"


def get_runtime_executable():
    if getattr(sys, "frozen", False):
        argv0 = os.path.abspath(sys.argv[0]) if sys.argv else ""
        if argv0.lower().endswith(".exe"):
            return argv0
        return os.path.abspath(sys.executable)
    return os.path.abspath(sys.executable)


def get_runtime_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(get_runtime_executable())
    return os.path.dirname(os.path.abspath(__file__))


def _normalize_path(path):
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _sibling_pythonw(path):
    if not path:
        return ""
    return os.path.join(os.path.dirname(os.path.abspath(path)), "pythonw.exe")


def _get_runtime_base_python():
    base_executable = getattr(sys, "_base_executable", "") or ""
    if base_executable:
        return os.path.abspath(base_executable)
    if sys.executable:
        return os.path.abspath(sys.executable)
    return ""


def get_preferred_python(windowless=False):
    candidates = []
    seen = set()

    def add_candidate(path):
        if not path:
            return
        candidate = os.path.abspath(path)
        normalized = _normalize_path(candidate)
        if normalized in seen:
            return
        seen.add(normalized)
        candidates.append(candidate)

    explicit = os.environ.get(PYTHONW_ENV_VAR if windowless else PYTHON_ENV_VAR, "").strip()
    add_candidate(explicit)

    explicit_console = os.environ.get(PYTHON_ENV_VAR, "").strip()
    if windowless and explicit_console:
        add_candidate(_sibling_pythonw(explicit_console))

    runtime_base_python = _get_runtime_base_python()
    if windowless and runtime_base_python:
        add_candidate(_sibling_pythonw(runtime_base_python))
    elif runtime_base_python:
        add_candidate(runtime_base_python)

    runtime_python = os.path.abspath(sys.executable) if sys.executable else ""
    if _normalize_path(runtime_python) != _normalize_path(runtime_base_python):
        if windowless and runtime_python:
            add_candidate(_sibling_pythonw(runtime_python))
        elif runtime_python:
            add_candidate(runtime_python)

    discovered = shutil.which("pythonw" if windowless else "python")
    add_candidate(discovered)

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    if runtime_base_python:
        return runtime_base_python
    return runtime_python if runtime_python else ("pythonw.exe" if windowless else "python.exe")


def get_venv_home(venv_dir):
    cfg_path = os.path.join(venv_dir, "pyvenv.cfg")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                key, _, value = raw_line.partition("=")
                if key.strip().lower() == "home":
                    return value.strip()
    except OSError:
        return ""
    return ""


def is_venv_healthy(venv_dir, preferred_python=""):
    scripts_dir = os.path.join(venv_dir, "Scripts")
    venv_python = os.path.join(scripts_dir, "python.exe")
    venv_pythonw = os.path.join(scripts_dir, "pythonw.exe")
    if not os.path.exists(venv_python) or not os.path.exists(venv_pythonw):
        return False

    venv_home = get_venv_home(venv_dir)
    if not venv_home:
        return False

    home_python = os.path.join(venv_home, "python.exe")
    if not os.path.exists(home_python):
        return False

    if preferred_python:
        expected_home = os.path.dirname(os.path.abspath(preferred_python))
        return _normalize_path(venv_home) == _normalize_path(expected_home)

    return True


def get_settings_dir():
    base = os.environ.get("APPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return os.path.join(base, APP_NAME)


def get_settings_path():
    return os.path.join(get_settings_dir(), SETTINGS_FILE)


def _normalize_dir(path):
    if not path:
        return ""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(path)))


def load_settings():
    path = get_settings_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_settings(settings):
    os.makedirs(get_settings_dir(), exist_ok=True)
    path = get_settings_path()
    payload = settings if isinstance(settings, dict) else {}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def get_cache_dir():
    settings = load_settings()
    cached = settings.get("cache_dir", "")
    normalized = _normalize_dir(cached)
    return normalized or DEFAULT_CACHE_DIR


def set_cache_dir(path):
    normalized = _normalize_dir(path)
    if not normalized:
        raise ValueError("cache_dir cannot be empty")
    settings = load_settings()
    settings["cache_dir"] = normalized
    save_settings(settings)
    return normalized
