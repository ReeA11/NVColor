"""Fluent dark tray context menu (compact WebView2 popup)."""

from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import webview

if TYPE_CHECKING:
    from controller import AppController

MENU_WIDTH = 200

user32 = ctypes.windll.user32


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _ui_file(name: str) -> str:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS) / "ui"  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent / "ui"
    return str(base / name)


def _cursor_pos() -> tuple[int, int]:
    pt = _POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def _hwnd_of(window: webview.Window | None) -> int:
    try:
        native = getattr(window, "native", None)
        if native is None:
            return 0
        return int(native.Handle.ToInt32())
    except Exception:
        return 0


def _point_in_window(hwnd: int, x: int, y: int) -> bool:
    if not hwnd:
        return False
    rc = _RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rc)):
        return False
    return rc.left <= x <= rc.right and rc.top <= y <= rc.bottom


class TrayMenuApi:
    """JS bridge — only public methods (no public attrs)."""

    def __init__(
        self,
        controller: AppController,
        *,
        on_settings: Callable[[], None],
        on_quit: Callable[[], None],
        on_folder: Callable[[], None],
        on_reset: Callable[[], None],
    ) -> None:
        self._controller = controller
        self._on_settings = on_settings
        self._on_quit = on_quit
        self._on_folder = on_folder
        self._on_reset = on_reset
        self._window: webview.Window | None = None
        self._height = 320
        self._lock = threading.Lock()
        self._visible = False
        self._ignore_dismiss_until = 0.0
        self._watch_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self._dismiss_hooked = False

    def get_menu_state(self) -> dict[str, Any]:
        lang = str(self._controller.cfg.get("ui_language") or "en").lower()
        return {
            "current": self._controller.current,
            "presets": list(self._controller.presets.keys()),
            "ui_language": "ru" if lang.startswith("ru") else "en",
        }

    def apply_preset(self, name: str) -> dict[str, Any]:
        try:
            self._controller.apply_named(name, reason="tray")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def action(self, name: str) -> dict[str, Any]:
        self.hide()
        if name == "settings":
            self._on_settings()
        elif name == "quit":
            self._on_quit()
        elif name == "folder":
            self._on_folder()
        elif name == "reset":
            self._on_reset()
        return {"ok": True}

    def report_height(self, height: int) -> dict[str, Any]:
        try:
            h = max(120, min(480, int(height) + 8))
            with self._lock:
                self._height = h
            window = self._window
            if window is not None and self._visible:
                window.resize(MENU_WIDTH, h)
        except Exception:
            pass
        return {"ok": True}

    def hide(self) -> dict[str, Any]:
        self._stop_outside_watch()
        self._visible = False
        window = self._window
        if window is None:
            return {"ok": True}
        try:
            window.hide()
        except Exception:
            pass
        return {"ok": True}

    def _attach_deactivate(self) -> None:
        if self._dismiss_hooked:
            return
        native = getattr(self._window, "native", None)
        if native is None:
            return

        def _on_deactivate(_sender=None, _args=None) -> None:
            if time.monotonic() < self._ignore_dismiss_until:
                return
            if self._visible:
                self.hide()

        try:
            native.Deactivate += _on_deactivate
            self._dismiss_hooked = True
        except Exception:
            pass

    def _start_outside_watch(self) -> None:
        self._stop_outside_watch()
        self._watch_stop = threading.Event()
        stop = self._watch_stop

        def _watch() -> None:
            # Let the menu grab focus / settle after open
            if stop.wait(0.25):
                return
            prev_down = False
            while not stop.is_set():
                if not self._visible:
                    break
                if time.monotonic() < self._ignore_dismiss_until:
                    stop.wait(0.05)
                    continue

                hwnd = _hwnd_of(self._window)
                fg = int(user32.GetForegroundWindow() or 0)
                # Another window took focus (and it's not us / our child)
                if hwnd and fg and fg != hwnd and not user32.IsChild(hwnd, fg):
                    self.hide()
                    break

                # Any mouse button click outside the menu rect
                left = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
                right = bool(user32.GetAsyncKeyState(0x02) & 0x8000)
                down = left or right
                if down and not prev_down:
                    x, y = _cursor_pos()
                    if not _point_in_window(hwnd, x, y):
                        self.hide()
                        break
                prev_down = down
                stop.wait(0.04)

        self._watch_thread = threading.Thread(target=_watch, name="tray-menu-dismiss", daemon=True)
        self._watch_thread.start()

    def _stop_outside_watch(self) -> None:
        stop = self._watch_stop
        stop.set()
        self._watch_thread = None

    def show_at_cursor(self) -> None:
        window = self._window
        if window is None:
            return
        try:
            # Toggle: second right-click closes
            if self._visible:
                self.hide()
                return

            x, y = _cursor_pos()
            with self._lock:
                h = self._height
            x = max(0, x - MENU_WIDTH)
            y = max(0, y - h)
            try:
                window.resize(MENU_WIDTH, h)
            except Exception:
                pass
            try:
                window.move(x, y)
            except Exception:
                pass

            self._ignore_dismiss_until = time.monotonic() + 0.35
            self._visible = True
            window.show()
            try:
                window.restore()
            except Exception:
                pass
            try:
                # Bring to foreground so Deactivate works later
                hwnd = _hwnd_of(window)
                if hwnd:
                    user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

            self._attach_deactivate()
            self._start_outside_watch()

            try:
                payload = self.get_menu_state()
                js = "window.refreshTrayMenu && window.refreshTrayMenu(" + json.dumps(payload) + ")"
                window.evaluate_js(js)
            except Exception:
                pass
        except Exception:
            self._visible = False


def create_tray_menu_window(
    controller: AppController,
    *,
    on_settings: Callable[[], None],
    on_quit: Callable[[], None],
    on_folder: Callable[[], None],
    on_reset: Callable[[], None],
    should_exit: Callable[[], bool] | None = None,
) -> tuple[webview.Window, TrayMenuApi]:
    api = TrayMenuApi(
        controller,
        on_settings=on_settings,
        on_quit=on_quit,
        on_folder=on_folder,
        on_reset=on_reset,
    )
    window = webview.create_window(
        "NVColor Menu",
        url=_ui_file("tray_menu.html"),
        js_api=api,
        width=MENU_WIDTH,
        height=320,
        frameless=True,
        easy_drag=False,
        on_top=True,
        focus=True,
        shadow=True,
        resizable=False,
        background_color="#2c2c2c",
        text_select=False,
        confirm_close=False,
        hidden=True,
        transparent=False,
    )
    api._window = window

    def _on_closing() -> bool | None:
        if should_exit and should_exit():
            return None
        try:
            api.hide()
        except Exception:
            pass
        return False

    window.events.closing += _on_closing
    return window, api
