r"""
cli_paste - Terminal Image Paste Helper

Global hooks for Ctrl+V and Right-Click:
- If the foreground window is a terminal AND the clipboard contains an image
  -> Save the image to disk
  -> Auto-type the file path
- Otherwise -> Pass through the original event
"""

import os
import sys
import time
import ctypes
import ctypes.wintypes
import threading
import hashlib
import getpass
from datetime import datetime

import win32gui
import win32process
import win32con
import win32clipboard
from PIL import Image, ImageGrab

from app_config import DEFAULT_CACHE_DIR, get_cache_dir, get_runtime_app_dir

# ── Config ────────────────────────────────────────────
APP_DIR = get_runtime_app_dir()
PID_FILE = os.path.join(APP_DIR, "cli_paste.pid")

MUTEX_NAME_HASH = hashlib.sha1(APP_DIR.lower().encode("utf-8")).hexdigest()[:16]
INSTANCE_MUTEX_NAME = f"Local\\cli_paste_{getpass.getuser().lower()}_{MUTEX_NAME_HASH}"
ERROR_ALREADY_EXISTS = 183

MAX_CACHE_FILES = 500
MAX_CACHE_AGE_DAYS = 7
CLEANUP_INTERVAL_SECONDS = 300

TERMINAL_PROCESSES = {
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "windowsterminal.exe",
    "wt.exe",
    "conhost.exe",
    "mintty.exe",
    "alacritty.exe",
    "wezterm-gui.exe",
    "hyper.exe",
    "terminus.exe",
    "tabby.exe",
    "git-bash.exe",
    "bash.exe",
    "wsl.exe",
    "openssh.exe",
    "ssh.exe",
    "fluent-terminal.exe",
    "cmder.exe",
    "console.exe",
    "kitty.exe",
    "putty.exe",
    "mobaxterm.exe",
    "xshell.exe",
    "securecrt.exe",
}

TERMINAL_CLASS_KEYWORDS = [
    "consolewindowclass",
    "pseudoconsolewindow",
    "mintty",
    "vt100",
    "terminal",
]

WINDOW_CACHE_TTL = 0.2


def _resolve_save_dir():
    preferred = get_cache_dir()
    candidates = [preferred]
    if preferred != DEFAULT_CACHE_DIR:
        candidates.append(DEFAULT_CACHE_DIR)
    candidates.append(
        os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), "cli_paste")
    )

    for candidate in candidates:
        if not candidate:
            continue
        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except Exception:
            continue

    raise RuntimeError("No writable cache directory for cli_paste")


SAVE_DIR = _resolve_save_dir()


# ── Utilities ─────────────────────────────────────────
_window_cache_hwnd = None
_window_cache_expire_at = 0.0
_window_cache_is_terminal = False
_window_cache_lock = threading.Lock()
_clipboard_cache_seq = -1
_clipboard_cache_has_image = False
_clipboard_cache_lock = threading.Lock()
_paste_worker_lock = threading.Lock()
_instance_mutex_handle = None
_cleanup_lock = threading.Lock()
_next_cleanup_at = 0.0
_swallow_rbutton_lock = threading.Lock()
_swallow_rbutton_up = False
_swallow_rbutton_deadline = 0.0
_active_workers = []
_workers_lock = threading.Lock()


def _write_pid_file():
    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def _clear_pid_file_if_owned():
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            pid_text = f.read().strip()
        if pid_text != str(os.getpid()):
            return
        os.remove(PID_FILE)
    except Exception:
        pass


def ensure_single_instance():
    global _instance_mutex_handle

    handle = ctypes.windll.kernel32.CreateMutexW(None, False, INSTANCE_MUTEX_NAME)
    if not handle:
        err = ctypes.windll.kernel32.GetLastError()
        raise RuntimeError(f"CreateMutexW failed: error={err}")

    last_err = ctypes.windll.kernel32.GetLastError()
    if last_err == ERROR_ALREADY_EXISTS:
        ctypes.windll.kernel32.CloseHandle(handle)
        return False

    _instance_mutex_handle = handle
    return True


def release_single_instance():
    global _instance_mutex_handle

    if _instance_mutex_handle:
        ctypes.windll.kernel32.CloseHandle(_instance_mutex_handle)
        _instance_mutex_handle = None


def _remove_file_silent(path):
    try:
        os.remove(path)
        return True
    except Exception:
        return False


def cleanup_saved_images():
    now_epoch = time.time()
    max_age_seconds = MAX_CACHE_AGE_DAYS * 24 * 60 * 60
    live_files = []

    try:
        names = os.listdir(SAVE_DIR)
    except Exception:
        return

    for name in names:
        if not name.lower().endswith(".png"):
            continue

        path = os.path.join(SAVE_DIR, name)
        try:
            st = os.stat(path)
        except Exception:
            continue

        if now_epoch - st.st_mtime > max_age_seconds:
            _remove_file_silent(path)
            continue

        live_files.append((st.st_mtime, path))

    if len(live_files) <= MAX_CACHE_FILES:
        return

    live_files.sort(key=lambda item: item[0])
    for _, path in live_files[:-MAX_CACHE_FILES]:
        _remove_file_silent(path)


def maybe_cleanup_saved_images():
    global _next_cleanup_at

    now = time.monotonic()
    if now < _next_cleanup_at:
        return
    if not _cleanup_lock.acquire(blocking=False):
        return

    try:
        _next_cleanup_at = now + CLEANUP_INTERVAL_SECONDS
        cleanup_saved_images()
    finally:
        _cleanup_lock.release()


def get_foreground_process_name(hwnd=None):
    try:
        if hwnd is None:
            hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return "", ""

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        class_name = win32gui.GetClassName(hwnd).lower()

        process_name = ""
        process_handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if process_handle and process_handle > 0:
            try:
                buf = ctypes.create_unicode_buffer(260)
                size = ctypes.wintypes.DWORD(len(buf))
                ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(
                    process_handle, 0, buf, ctypes.byref(size),
                )
                if ok:
                    process_name = os.path.basename(buf.value).lower()
            finally:
                ctypes.windll.kernel32.CloseHandle(process_handle)

        return process_name, class_name
    except Exception:
        return "", ""


def is_terminal_window(hwnd=None):
    global _window_cache_hwnd, _window_cache_expire_at, _window_cache_is_terminal

    if hwnd is None:
        hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return False

    with _window_cache_lock:
        now = time.monotonic()
        if hwnd == _window_cache_hwnd and now < _window_cache_expire_at:
            return _window_cache_is_terminal

        proc_name, class_name = get_foreground_process_name(hwnd)
        is_terminal = proc_name in TERMINAL_PROCESSES

        # VSCode/JetBrains IDE 集成终端检测
        if not is_terminal and proc_name in ("code.exe", "code - insiders.exe"):
            try:
                title = win32gui.GetWindowText(hwnd).lower()
                if any(kw in title for kw in ["terminal", "powershell", "bash", "cmd", "wsl"]):
                    is_terminal = True
            except Exception:
                pass

        if not is_terminal:
            for kw in TERMINAL_CLASS_KEYWORDS:
                if kw in class_name:
                    is_terminal = True
                    break

        _window_cache_hwnd = hwnd
        _window_cache_expire_at = now + WINDOW_CACHE_TTL
        _window_cache_is_terminal = is_terminal
        return is_terminal


def clipboard_has_image():
    global _clipboard_cache_seq, _clipboard_cache_has_image

    try:
        seq = ctypes.windll.user32.GetClipboardSequenceNumber()
        with _clipboard_cache_lock:
            if seq and seq == _clipboard_cache_seq:
                return _clipboard_cache_has_image

            has = bool(
                win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB)
                or win32clipboard.IsClipboardFormatAvailable(win32con.CF_BITMAP)
            )
            _clipboard_cache_seq = seq
            _clipboard_cache_has_image = has
            return has
    except Exception:
        return False


def _open_clipboard_with_retry(retries=5, delay=0.01):
    for _ in range(retries):
        try:
            win32clipboard.OpenClipboard()
            return True
        except Exception:
            time.sleep(delay)
    return False


def save_clipboard_image():
    try:
        img = ImageGrab.grabclipboard()
        if img is None:
            return None
        if not isinstance(img, Image.Image):
            return None

        # 生成唯一文件名，避免覆盖
        for attempt in range(100):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"clip_{timestamp}.png"
            filepath = os.path.join(SAVE_DIR, filename)
            if not os.path.exists(filepath):
                break
            time.sleep(0.001)
        else:
            return None

        img.save(filepath, "PNG")
        return filepath
    except Exception as e:
        print(f"[cli_paste] Failed to save image: {e}", file=sys.stderr)
        return None


def paste_filepath(filepath, release_ctrl=False):
    """Put file path into clipboard and simulate Ctrl+V."""
    user32 = ctypes.windll.user32

    if release_ctrl:
        # Keyboard trigger may still have Ctrl physically down. Release first so
        # we do not produce duplicate modified key sequences in the target app.
        time.sleep(0.03)
        user32.keybd_event(0x11, 0, 0x0002, 0)  # Ctrl up
    if not _open_clipboard_with_retry():
        print("[cli_paste] Clipboard is busy, skip this paste", file=sys.stderr)
        return False

    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(filepath, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()

    time.sleep(0.01)
    send_ctrl_v()
    return True


def _is_same_foreground_window(hwnd):
    try:
        return bool(hwnd) and win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False


def _handle_image_paste_worker(trigger, target_hwnd):
    try:
        filepath = save_clipboard_image()
        if filepath:
            if _is_same_foreground_window(target_hwnd):
                paste_filepath(filepath, release_ctrl=(trigger == "keyboard"))
            return

        if trigger == "keyboard" and _is_same_foreground_window(target_hwnd):
            send_ctrl_v()
    finally:
        try:
            maybe_cleanup_saved_images()
        finally:
            _paste_worker_lock.release()


def handle_image_paste(trigger):
    """Schedule background image handling. Returns True if the event should be swallowed."""
    target_hwnd = win32gui.GetForegroundWindow()
    if not target_hwnd:
        return False
    if not is_terminal_window(target_hwnd):
        return False
    if not clipboard_has_image():
        return False

    if not _paste_worker_lock.acquire(blocking=False):
        return trigger == "keyboard"

    try:
        worker = threading.Thread(
            target=_handle_image_paste_worker,
            args=(trigger, target_hwnd),
            daemon=False,
        )
        with _workers_lock:
            _active_workers.append(worker)
        worker.start()
    except Exception:
        _paste_worker_lock.release()
        raise

    return True


# ── SendInput structures ──────────────────────────────

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT),
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", _INPUT_UNION),
    ]


def _make_unicode_input(char, flags):
    inp = INPUT()
    inp.type = 1  # INPUT_KEYBOARD
    inp.union.ki.wVk = 0
    inp.union.ki.wScan = ord(char)
    inp.union.ki.dwFlags = flags
    inp.union.ki.time = 0
    inp.union.ki.dwExtraInfo = None
    return inp


def send_ctrl_v():
    user32 = ctypes.windll.user32
    VK_CONTROL = 0x11
    VK_V = 0x56
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    time.sleep(0.002)
    user32.keybd_event(VK_V, 0, 0, 0)
    time.sleep(0.002)
    user32.keybd_event(VK_V, 0, 0x0002, 0)
    time.sleep(0.002)
    user32.keybd_event(VK_CONTROL, 0, 0x0002, 0)


# ── Low-level keyboard hook ──────────────────────────

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
VK_V = 0x56
VK_CONTROL = 0x11

LLKHF_INJECTED = 0x00000010

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.c_ulong),
        ("scanCode", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


def low_level_keyboard_proc(nCode, wParam, lParam):
    if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
        kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents

        if kb.flags & LLKHF_INJECTED:
            return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

        # Ctrl+V
        if kb.vkCode == VK_V:
            ctrl_pressed = (ctypes.windll.user32.GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0
            if ctrl_pressed:
                try:
                    if handle_image_paste("keyboard"):
                        return 1  # swallow the key
                except Exception as e:
                    print(f"[cli_paste] Error: {e}", file=sys.stderr)

    return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)


if ctypes.sizeof(ctypes.c_void_p) == 8:
    LRESULT = ctypes.c_longlong
else:
    LRESULT = ctypes.c_long


HOOKPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)

ctypes.windll.user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
]
ctypes.windll.user32.CallNextHookEx.restype = LRESULT

_kb_hook_callback = HOOKPROC(low_level_keyboard_proc)


# ── Low-level mouse hook ─────────────────────────────

WH_MOUSE_LL = 14
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]

LLMHF_INJECTED = 0x00000001


def low_level_mouse_proc(nCode, wParam, lParam):
    global _swallow_rbutton_up, _swallow_rbutton_deadline

    if nCode >= 0 and wParam in (WM_RBUTTONDOWN, WM_RBUTTONUP):
        ms = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents

        if ms.flags & LLMHF_INJECTED:
            return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

        if wParam == WM_RBUTTONDOWN:
            try:
                if handle_image_paste("mouse"):
                    with _swallow_rbutton_lock:
                        _swallow_rbutton_up = True
                        _swallow_rbutton_deadline = time.monotonic() + 2.0
                    return 1
            except Exception as e:
                print(f"[cli_paste] Error: {e}", file=sys.stderr)
        elif wParam == WM_RBUTTONUP:
            with _swallow_rbutton_lock:
                if _swallow_rbutton_up:
                    now = time.monotonic()
                    should_swallow = now <= _swallow_rbutton_deadline
                    _swallow_rbutton_up = False
                    _swallow_rbutton_deadline = 0.0
                    if should_swallow:
                        return 1

    return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)


MOUSEHOOKPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)

_mouse_hook_callback = MOUSEHOOKPROC(low_level_mouse_proc)


# ── Hook install ──────────────────────────────────────

def install_hooks():
    kb_hook = ctypes.windll.user32.SetWindowsHookExW(
        WH_KEYBOARD_LL, _kb_hook_callback, None, 0,
    )
    if not kb_hook:
        err = ctypes.windll.kernel32.GetLastError()
        raise RuntimeError(f"Keyboard hook failed: error={err}")

    mouse_hook = ctypes.windll.user32.SetWindowsHookExW(
        WH_MOUSE_LL, _mouse_hook_callback, None, 0,
    )
    if not mouse_hook:
        err = ctypes.windll.kernel32.GetLastError()
        ctypes.windll.user32.UnhookWindowsHookEx(kb_hook)
        raise RuntimeError(f"Mouse hook failed: error={err}")

    return kb_hook, mouse_hook


def message_loop():
    msg = ctypes.wintypes.MSG()
    while True:
        result = ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if result == -1:
            err = ctypes.windll.kernel32.GetLastError()
            raise RuntimeError(f"GetMessageW failed: error={err}")
        if result == 0:
            break
        ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
        ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))


# ── Entry point ───────────────────────────────────────

def _wait_for_workers(timeout=5.0):
    """等待所有活动的 worker 线程完成"""
    with _workers_lock:
        workers = list(_active_workers)

    deadline = time.time() + timeout
    for worker in workers:
        remaining = deadline - time.time()
        if remaining > 0:
            worker.join(timeout=remaining)


def main():
    if not ensure_single_instance():
        print("[cli_paste] Another instance is already running. Exit.")
        return

    _write_pid_file()
    maybe_cleanup_saved_images()

    print("[cli_paste] Starting...")
    print(f"[cli_paste] Image cache: {SAVE_DIR}")
    print("[cli_paste] Ctrl+V / Right-click in terminal with image in clipboard -> auto file path")
    print("[cli_paste] Press Ctrl+C to exit")
    print()

    kb_hook = None
    mouse_hook = None
    try:
        kb_hook, mouse_hook = install_hooks()
        message_loop()
    except KeyboardInterrupt:
        print("\n[cli_paste] Exiting, waiting for pending operations...")
        _wait_for_workers()
        print("[cli_paste] Exited")
    finally:
        if kb_hook:
            ctypes.windll.user32.UnhookWindowsHookEx(kb_hook)
        if mouse_hook:
            ctypes.windll.user32.UnhookWindowsHookEx(mouse_hook)
        _clear_pid_file_if_owned()
        release_single_instance()


if __name__ == "__main__":
    main()
