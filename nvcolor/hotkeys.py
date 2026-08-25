"""Global hotkeys via RegisterHotKey (stable rebind, no thread churn)."""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_USER = 0x0400
WM_REBIND = WM_USER + 77

PM_NOREMOVE = 0x0000

RegisterHotKey = user32.RegisterHotKey
RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
RegisterHotKey.restype = wintypes.BOOL

UnregisterHotKey = user32.UnregisterHotKey
UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
UnregisterHotKey.restype = wintypes.BOOL

GetMessageW = user32.GetMessageW
PeekMessageW = user32.PeekMessageW
TranslateMessage = user32.TranslateMessage
DispatchMessageW = user32.DispatchMessageW
PostThreadMessageW = user32.PostThreadMessageW
PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
PostThreadMessageW.restype = wintypes.BOOL


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("lPrivate", wintypes.DWORD),
    ]


_VK_MAP = {
    **{str(i): 0x30 + i for i in range(10)},
    **{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
    **{chr(c): c for c in range(ord("a"), ord("z") + 1)},
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
    # Shifted punctuation → underlying digit/key VK
    "parenright": 0x30,  # Shift+0
    "parenleft": 0x39,  # Shift+9
    "exclam": 0x31,
    "at": 0x32,
    "numbersign": 0x33,
    "dollar": 0x34,
    "percent": 0x35,
    "asciicircum": 0x36,
    "ampersand": 0x37,
    "asterisk": 0x38,
    "!": 0x31,
    "@": 0x32,
    "#": 0x33,
    "$": 0x34,
    "%": 0x35,
    "^": 0x36,
    "&": 0x37,
    "*": 0x38,
    "(": 0x39,
    ")": 0x30,
    "minus": 0xBD,
    "equal": 0xBB,
    "plus": 0xBB,
    "underscore": 0xBD,
    "-": 0xBD,
    "=": 0xBB,
    "_": 0xBD,
    "+": 0xBB,
}

# Shifted char → canonical unshifted key token for storage/display
_SHIFT_TO_KEY = {
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "exclam": "1",
    "at": "2",
    "numbersign": "3",
    "dollar": "4",
    "percent": "5",
    "asciicircum": "6",
    "ampersand": "7",
    "asterisk": "8",
    "parenleft": "9",
    "parenright": "0",
    "underscore": "-",
    "plus": "=",
}

_MOD_ORDER = ("alt", "ctrl", "shift", "win")
_MOD_LABEL = {"alt": "Alt", "ctrl": "Ctrl", "shift": "Shift", "win": "Win"}


def _canonical_key_token(part: str) -> str:
    p = part.strip().lower()
    if p in _SHIFT_TO_KEY:
        return _SHIFT_TO_KEY[p]
    if p.startswith("f") and p[1:].isdigit():
        return p  # f7
    if len(p) == 1 and p.isalpha():
        return p
    return p


def format_hotkey(spec: str) -> str:
    """Normalize to display form: Alt+Ctrl+Shift+3."""
    parts = [p.strip().lower() for p in (spec or "").replace("-", "+").split("+") if p.strip()]
    if not parts:
        return ""
    mods: list[str] = []
    key: str | None = None
    for part in parts:
        if part in ("alt", "menu"):
            mods.append("alt")
        elif part in ("ctrl", "control"):
            mods.append("ctrl")
        elif part == "shift":
            mods.append("shift")
        elif part in ("win", "windows", "super", "meta"):
            mods.append("win")
        else:
            key = _canonical_key_token(part)
    if key is None:
        return ""
    ordered = [_MOD_LABEL[m] for m in _MOD_ORDER if m in mods]
    key_label = key.upper() if (key.startswith("f") and key[1:].isdigit()) or (len(key) == 1 and key.isalpha()) else key
    return "+".join([*ordered, key_label])


def parse_hotkey(spec: str) -> tuple[int, int]:
    """Parse 'alt+shift+1' / 'Alt+Shift+3' → (modifiers, vk)."""
    parts = [p.strip().lower() for p in spec.replace("-", "+").split("+") if p.strip()]
    if not parts:
        raise ValueError(f"Empty hotkey: {spec!r}")

    mods = MOD_NOREPEAT
    key = None
    for part in parts:
        if part in ("alt", "menu"):
            mods |= MOD_ALT
        elif part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part in ("win", "windows", "super", "meta"):
            mods |= MOD_WIN
        else:
            if key is not None:
                raise ValueError(f"Multiple keys in hotkey: {spec!r}")
            token = _canonical_key_token(part)
            if token not in _VK_MAP:
                raise ValueError(f"Unknown key in hotkey: {part!r}")
            key = _VK_MAP[token]
    if key is None:
        raise ValueError(f"No key in hotkey: {spec!r}")
    return mods, key


def _ensure_message_queue() -> None:
    """Create a thread message queue so PostThreadMessage / RegisterHotKey work."""
    msg = MSG()
    PeekMessageW(ctypes.byref(msg), None, WM_USER, WM_USER, PM_NOREMOVE)


class HotkeyListener:
    """
    One long-lived thread owns all RegisterHotKey calls.

    Rebinding (after Save preset) happens on THAT thread via WM_REBIND,
    so we never hit ERROR_HOTKEY_ALREADY_REGISTERED from a second thread.
    """

    def __init__(self) -> None:
        self._bindings: dict[int, tuple[str, Callable[[], None]]] = {}
        self._pending: dict[int, tuple[str, Callable[[], None]]] | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._rebound = threading.Event()
        self._error: Exception | None = None
        self._registered_ids: list[int] = []

    def bind(self, hotkey_id: int, spec: str, callback: Callable[[], None]) -> None:
        with self._lock:
            self._bindings[hotkey_id] = (spec, callback)

    def clear_bindings(self) -> None:
        with self._lock:
            self._bindings.clear()

    def start(self) -> None:
        """Start listener, or rebind if already running (waits for completion)."""
        self.start_or_rebind()

    def set_bindings(self, bindings: dict[int, tuple[str, Callable[[], None]]]) -> None:
        """Replace all hotkeys atomically and wait until registered."""
        with self._lock:
            self._bindings = dict(bindings)
        self.start_or_rebind()

    def start_or_rebind(self) -> None:
        with self._lock:
            alive = bool(self._thread and self._thread.is_alive())
            if alive and self._thread_id:
                self._pending = dict(self._bindings)
                self._rebound.clear()
                self._error = None
                tid = self._thread_id
            else:
                tid = None
                self._ready.clear()
                self._rebound.clear()
                self._error = None
                self._thread = threading.Thread(target=self._run, name="HotkeyListener", daemon=True)
                self._thread.start()

        if tid is not None:
            if not PostThreadMessageW(tid, WM_REBIND, 0, 0):
                time.sleep(0.05)
                PostThreadMessageW(tid, WM_REBIND, 0, 0)
            if not self._rebound.wait(timeout=5):
                raise TimeoutError("Hotkey rebind timed out")
            if self._error:
                raise self._error
            return

        if not self._ready.wait(timeout=5):
            raise TimeoutError("Hotkey listener failed to start")
        if self._error:
            raise self._error

    def stop(self) -> None:
        tid = self._thread_id
        if tid is not None:
            # Several quits — PostThreadMessage can be dropped if queue is busy
            for _ in range(3):
                PostThreadMessageW(tid, WM_QUIT, 0, 0)
                time.sleep(0.01)
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        self._thread_id = None
        self._registered_ids = []

    def _unregister_all(self) -> None:
        for hotkey_id in self._registered_ids:
            UnregisterHotKey(None, hotkey_id)
        self._registered_ids = []

    def _register_all(self, bindings: dict[int, tuple[str, Callable[[], None]]]) -> None:
        self._unregister_all()
        errors: list[str] = []
        for hotkey_id, (spec, _cb) in bindings.items():
            if not spec:
                continue
            try:
                mods, vk = parse_hotkey(spec)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            ctypes.set_last_error(0)
            if not RegisterHotKey(None, hotkey_id, mods, vk):
                err = ctypes.get_last_error()
                errors.append(f"{spec!r} (winerror={err})")
                continue
            self._registered_ids.append(hotkey_id)
            print(f"[NVColor] Hotkey {spec} registered (id={hotkey_id})", flush=True)
        if errors and not self._registered_ids:
            raise OSError("RegisterHotKey failed: " + "; ".join(errors))
        if errors:
            print(f"[NVColor] Some hotkeys failed: {'; '.join(errors)}", flush=True)

    def _run(self) -> None:
        _ensure_message_queue()
        self._thread_id = kernel32.GetCurrentThreadId()
        try:
            with self._lock:
                initial = dict(self._bindings)
            self._register_all(initial)
            self._ready.set()

            msg = MSG()
            while True:
                result = GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0:  # WM_QUIT
                    break
                if result == -1:
                    break

                if msg.message == WM_REBIND:
                    with self._lock:
                        pending = self._pending if self._pending is not None else dict(self._bindings)
                        self._pending = None
                        self._bindings = dict(pending)
                    try:
                        self._register_all(pending)
                        self._error = None
                    except Exception as exc:
                        self._error = exc
                    self._rebound.set()
                    continue

                if msg.message == WM_HOTKEY:
                    hid = int(msg.wParam)
                    with self._lock:
                        binding = self._bindings.get(hid)
                    if binding:
                        _spec, callback = binding
                        try:
                            callback()
                        except Exception:
                            pass
                    continue

                TranslateMessage(ctypes.byref(msg))
                DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self._error = exc
            self._ready.set()
            self._rebound.set()
        finally:
            self._unregister_all()
            self._thread_id = None
