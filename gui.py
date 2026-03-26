"""
cli_paste Control Panel
Manage the cli_paste background process, settings, and autostart.
"""

import csv
import ctypes
import io
import os
import subprocess
import sys
import tkinter as tk
import xml.etree.ElementTree as ET
from tkinter import filedialog, messagebox

from app_config import (
    get_cache_dir,
    get_preferred_python,
    get_runtime_app_dir,
    get_runtime_executable,
    set_cache_dir,
)

# Constants
APP_DIR = get_runtime_app_dir()
PACKAGED_EXE = os.path.join(APP_DIR, "dist", "cli_paste.exe")
VENV_PYTHON = os.path.join(APP_DIR, ".venv", "Scripts", "python.exe")
VENV_PYTHONW = os.path.join(APP_DIR, ".venv", "Scripts", "pythonw.exe")
BOOTSTRAP_SCRIPT = os.path.join(APP_DIR, "bootstrap.py")
GUI_SCRIPT = os.path.join(APP_DIR, "gui.py")
PID_FILE = os.path.join(APP_DIR, "cli_paste.pid")
TASK_NAME = "cli_paste_autostart"
WORKER_ARG = "--worker"
CREATE_NO_WINDOW = 0x08000000


def _get_packaged_executable():
    if getattr(sys, "frozen", False):
        return get_runtime_executable()
    if os.path.exists(PACKAGED_EXE):
        return PACKAGED_EXE
    return ""


def _get_worker_command():
    packaged_exe = _get_packaged_executable()
    if packaged_exe:
        return [packaged_exe, WORKER_ARG]

    python_exe = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable
    return [python_exe, GUI_SCRIPT, WORKER_ARG]


def _get_windowless_python():
    return get_preferred_python(windowless=True)


def _get_startup_task_command():
    packaged_exe = _get_packaged_executable()
    if packaged_exe:
        return [packaged_exe, WORKER_ARG]

    return [_get_windowless_python(), BOOTSTRAP_SCRIPT, WORKER_ARG]


def _get_worker_commandline():
    return subprocess.list2cmdline(_get_worker_command())


def _get_startup_task_commandline():
    return subprocess.list2cmdline(_get_startup_task_command())


def _run_worker_entrypoint():
    import cli_paste

    cli_paste.main()


def _clear_topmost(window):
    try:
        window.attributes("-topmost", False)
    except Exception:
        pass


def _restore_window(window):
    try:
        if window.state() != "normal":
            window.deiconify()
            window.state("normal")
    except Exception:
        pass

    try:
        window.lift()
    except Exception:
        pass

    try:
        window.attributes("-topmost", True)
        window.after_idle(lambda: _clear_topmost(window))
    except Exception:
        _clear_topmost(window)

    try:
        window.focus_force()
    except Exception:
        pass


# Process detection
def _is_pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False

    try:
        r = subprocess.run(
            ["tasklist", "/fi", f"PID eq {pid}", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            return False

        for row in csv.reader(io.StringIO(r.stdout)):
            if len(row) < 2:
                continue
            try:
                if int(row[1]) == pid:
                    return True
            except ValueError:
                continue
        return False
    except Exception:
        return False


def _save_pid(pid):
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(pid))


def _load_pid():
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return None


def _clear_pid():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def _kill_pid(pid):
    try:
        subprocess.run(
            ["taskkill", "/f", "/pid", str(pid)],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        pass


# Task Scheduler
def is_task_exists():
    try:
        r = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except Exception:
        return False


def _normalize_cli_token(token):
    value = (token or "").strip().strip('"')
    if not value:
        return ""

    if any(sep in value for sep in ("\\", "/")) or value.lower().endswith((".py", ".exe", ".bat", ".cmd")):
        return os.path.normcase(os.path.normpath(value))

    return value


def _split_windows_commandline(text):
    if text is None:
        return []

    value = text.strip()
    if not value:
        return []

    try:
        command_line_to_argv = ctypes.windll.shell32.CommandLineToArgvW
        command_line_to_argv.argtypes = [ctypes.wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
        command_line_to_argv.restype = ctypes.POINTER(ctypes.wintypes.LPWSTR)

        local_free = ctypes.windll.kernel32.LocalFree
        local_free.argtypes = [ctypes.wintypes.HLOCAL]
        local_free.restype = ctypes.wintypes.HLOCAL

        argc = ctypes.c_int()
        argv = command_line_to_argv(value, ctypes.byref(argc))
        if not argv:
            return []
        try:
            return [argv[i] for i in range(argc.value)]
        finally:
            local_free(argv)
    except Exception:
        return value.split()


def _task_definition_matches_command(xml_text, expected_command):
    if not xml_text:
        return False

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return False

    exec_node = None
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] == "Exec":
            exec_node = node
            break

    if exec_node is None:
        return False

    command_text = ""
    arguments_text = ""
    for child in exec_node:
        tag_name = child.tag.rsplit("}", 1)[-1]
        if tag_name == "Command":
            command_text = (child.text or "").strip()
        elif tag_name == "Arguments":
            arguments_text = (child.text or "").strip()

    actual_tokens = [_normalize_cli_token(command_text)]
    actual_tokens.extend(_normalize_cli_token(token) for token in _split_windows_commandline(arguments_text))

    expected_tokens = [_normalize_cli_token(token) for token in expected_command]
    return actual_tokens == expected_tokens


def _get_startup_task_xml():
    try:
        r = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME, "/xml"],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            return None
        return r.stdout
    except Exception:
        return None


def is_task_current():
    xml_text = _get_startup_task_xml()
    return _task_definition_matches_command(xml_text, _get_startup_task_command())


def create_startup_task():
    cmd = [
        "schtasks",
        "/create",
        "/tn",
        TASK_NAME,
        "/tr",
        _get_startup_task_commandline(),
        "/sc",
        "onlogon",
        "/rl",
        "highest",
        "/f",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    return r.returncode == 0


def delete_startup_task():
    r = subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True,
        creationflags=CREATE_NO_WINDOW,
    )
    return r.returncode == 0


class App:
    def __init__(self):
        self._pid = None

        self.root = tk.Tk()
        self.root.title("cli_paste")
        self.root.resizable(False, False)

        w, h = 500, 260
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.bind("<Map>", self._on_root_mapped, add="+")

        self.status_var = tk.StringVar(value="Status: Stopped")
        tk.Label(self.root, textvariable=self.status_var, font=("Segoe UI", 11)).pack(pady=(15, 8))

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=4)

        self.start_btn = tk.Button(btn_frame, text="Start", width=10, command=self.start_process)
        self.start_btn.grid(row=0, column=0, padx=8)

        self.stop_btn = tk.Button(btn_frame, text="Stop", width=10, command=self.stop_process, state=tk.DISABLED)
        self.stop_btn.grid(row=0, column=1, padx=8)

        self.settings_btn = tk.Button(btn_frame, text="Settings", width=10, command=self.open_settings)
        self.settings_btn.grid(row=0, column=2, padx=8)

        cache_frame = tk.LabelFrame(self.root, text="Image Cache")
        cache_frame.pack(fill="x", padx=14, pady=(10, 6))

        self.cache_dir_var = tk.StringVar(value=get_cache_dir())
        tk.Label(
            cache_frame,
            textvariable=self.cache_dir_var,
            justify="left",
            anchor="w",
            wraplength=455,
        ).pack(fill="x", padx=8, pady=(5, 8))

        if is_task_exists() and not is_task_current():
            create_startup_task()

        self.autostart_var = tk.BooleanVar(value=is_task_exists() and is_task_current())
        tk.Checkbutton(
            self.root,
            text="Run at login (Task Scheduler)",
            variable=self.autostart_var,
            command=self.toggle_autostart,
        ).pack(pady=(6, 0))

        saved_pid = _load_pid()
        if saved_pid and _is_pid_alive(saved_pid):
            self._pid = saved_pid
        else:
            _clear_pid()

        self._poll()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after_idle(lambda: _restore_window(self.root))

    def start_process(self):
        if self._is_running():
            return
        try:
            cmd = _get_worker_command()
            if not getattr(sys, "frozen", False):
                if not os.path.exists(cmd[0]):
                    messagebox.showerror("Error", f"Executable not found: {cmd[0]}")
                    return
                if not cmd[0].lower().endswith(".exe") and not os.path.exists(GUI_SCRIPT):
                    messagebox.showerror("Error", f"gui.py not found: {GUI_SCRIPT}")
                    return

            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0

            log_file = open(os.path.join(APP_DIR, "cli_paste.log"), "a", encoding="utf-8")
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=APP_DIR,
                    stdout=log_file,
                    stderr=log_file,
                    stdin=subprocess.DEVNULL,
                    startupinfo=si,
                    creationflags=CREATE_NO_WINDOW,
                )
            finally:
                log_file.close()

            self._pid = proc.pid
            _save_pid(proc.pid)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start: {e}")

    def stop_process(self):
        if self._pid and _is_pid_alive(self._pid):
            _kill_pid(self._pid)
        self._pid = None
        _clear_pid()

    def _is_running(self):
        return self._pid is not None and _is_pid_alive(self._pid)

    def _apply_cache_dir(self, new_dir):
        target = os.path.abspath(os.path.expandvars(os.path.expanduser(new_dir.strip())))
        if not target:
            raise ValueError("Cache directory cannot be empty")
        os.makedirs(target, exist_ok=True)
        saved = set_cache_dir(target)
        self.cache_dir_var.set(saved)

        if self._is_running():
            self.stop_process()
            self.start_process()

    def open_settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("620x145")

        path_var = tk.StringVar(value=self.cache_dir_var.get())

        tk.Label(dialog, text="Global image cache directory:").pack(anchor="w", padx=12, pady=(12, 5))

        entry_frame = tk.Frame(dialog)
        entry_frame.pack(fill="x", padx=12)

        entry = tk.Entry(entry_frame, textvariable=path_var, width=72)
        entry.pack(side="left", fill="x", expand=True)

        def browse_dir():
            current = path_var.get().strip()
            initial = current if os.path.isdir(current) else os.path.expanduser("~")
            picked = filedialog.askdirectory(parent=dialog, initialdir=initial)
            if picked:
                path_var.set(picked)

        tk.Button(entry_frame, text="Browse...", command=browse_dir, width=10).pack(side="left", padx=(8, 0))

        def save_and_close():
            try:
                self._apply_cache_dir(path_var.get())
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save settings: {e}", parent=dialog)
                return

            messagebox.showinfo(
                "Saved",
                "Cache directory saved. If cli_paste was running, it has been restarted.",
                parent=dialog,
            )
            dialog.destroy()

        footer = tk.Frame(dialog)
        footer.pack(fill="x", padx=12, pady=(12, 10))
        tk.Button(footer, text="Cancel", width=9, command=dialog.destroy).pack(side="right")
        tk.Button(footer, text="Save", width=9, command=save_and_close).pack(side="right", padx=(0, 8))

        entry.focus_set()

    def toggle_autostart(self):
        if self.autostart_var.get():
            if not create_startup_task():
                messagebox.showerror("Error", "Failed to create startup task. Run as administrator.")
                self.autostart_var.set(False)
        else:
            if not delete_startup_task():
                messagebox.showerror("Error", "Failed to delete startup task.")
                self.autostart_var.set(True)

    def _poll(self):
        running = self._is_running()
        self.status_var.set("Status: Running" if running else "Status: Stopped")
        self.start_btn.config(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_btn.config(state=tk.NORMAL if running else tk.DISABLED)
        self.root.after(1000, self._poll)

    def _on_root_mapped(self, event):
        if event.widget is not self.root:
            return
        self.root.after_idle(lambda: _restore_window(self.root))

    def _on_close(self):
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if WORKER_ARG in sys.argv[1:]:
        _run_worker_entrypoint()
    else:
        App().run()
