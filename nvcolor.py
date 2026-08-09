"""
NVColor — WebView2 settings UI + system tray.

System layer stays Python (gamma, hotkeys, watcher, config).
Settings window is Fluent HTML in Edge WebView2 via pywebview.
pystray.run() on a worker thread; webview.start() owns the main thread.
"""

from __future__ import annotations

import atexit
import sys
import threading
import traceback
from pathlib import Path

from PIL import Image

from config_store import app_dir, config_path
from controller import AppController
from gamma_control import hard_reset as apply_hard_reset
from nvapi_color import reset_nv_color
from settings_webview import SettingsApi, create_settings_window, resource_dir
from tray_menu import TrayMenuApi, create_tray_menu_window

try:
    import pystray
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install dependencies: pip install -r requirements.txt") from exc

try:
    import webview
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install dependencies: pip install -r requirements.txt") from exc


APP_NAME = "NVColor"
MUTEX_NAME = "Local\\NVColorSingleInstance"
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205


def _log(msg: str) -> None:
    try:
        print(f"[NVColor] {msg.rstrip()}", flush=True)
    except Exception:
        pass


def _message_box(title: str, text: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, title, 0x00000040)
    except Exception:
        pass


def icon_png_path() -> Path:
    return resource_dir() / "assets" / "nvcolor.png"


def icon_ico_path() -> Path:
    bundled = resource_dir() / "assets" / "nvcolor.ico"
    if bundled.is_file():
        return bundled
    # Dev fallback next to project
    local = Path(__file__).resolve().parent / "assets" / "nvcolor.ico"
    return local


def make_icon() -> Image.Image:
    """Tray icon from branded NVColor asset (fallback: solid mark)."""
    path = icon_png_path()
    if not path.is_file():
        path = Path(__file__).resolve().parent / "assets" / "nvcolor.png"
    try:
        img = Image.open(path).convert("RGBA")
        return img.resize((64, 64), Image.Resampling.LANCZOS)
    except Exception:
        size = 64
        img = Image.new("RGBA", (size, size), (28, 28, 28, 255))
        return img


class FluentTrayIcon(pystray.Icon):
    """pystray icon that opens a custom Fluent menu on right-click."""

    def __init__(self, *args, on_left=None, on_right=None, **kwargs):
        self._on_left = on_left
        self._on_right = on_right
        super().__init__(*args, **kwargs)

    def _on_notify(self, wparam, lparam):  # noqa: ANN001
        if lparam == WM_LBUTTONUP:
            if self._on_left:
                self._on_left()
            else:
                self()
        elif lparam == WM_RBUTTONUP:
            if self._on_right:
                self._on_right()


class TrayApp:
    def __init__(self) -> None:
        self.controller = AppController()
        self.window: webview.Window | None = None
        self.api: SettingsApi | None = None
        self.menu_window: webview.Window | None = None
        self.menu_api: TrayMenuApi | None = None
        self.icon: pystray.Icon | None = None
        self._tray_thread: threading.Thread | None = None
        self._exiting = False
        self._gui_ready = threading.Event()

        self.controller.notify_cb = self._tray_notify
        self.controller.start_services()

    def _tray_notify(self, text: str) -> None:
        if self.icon is None:
            return
        try:
            self.icon.notify(text, APP_NAME)
        except Exception:
            pass

    def open_settings(self, icon=None, item=None) -> None:  # noqa: ANN001, ARG001
        try:
            if self.menu_api is not None:
                self.menu_api.hide()
            if self.window is None:
                return
            self.window.show()
            try:
                self.window.restore()
            except Exception:
                pass
            if self.api is not None:
                self.api._push_refresh()
            _log("Settings window shown")
        except Exception:
            err = traceback.format_exc()
            _log("Failed to show settings:\n" + err)
            _message_box(APP_NAME, f"Не удалось открыть настройки.\n\n{err[-700:]}")

    def _show_tray_menu(self) -> None:
        try:
            if self.menu_api is not None:
                self.menu_api.show_at_cursor()
        except Exception:
            _log("Tray menu failed:\n" + traceback.format_exc())

    def _on_settings_hidden(self) -> None:
        _log("Settings hidden → tray unchanged")
        self._tray_notify("Свёрнуто в трей. ПКМ по иконке — меню.")

    def _hard_reset_menu(self) -> None:
        self.controller.hard_reset()

    def _open_folder(self) -> None:
        import os

        os.startfile(str(app_dir()))  # noqa: S606

    def quit_app(self, icon=None, item=None) -> None:  # noqa: ANN001, ARG001
        if self._exiting:
            return
        self._exiting = True
        _log("Quit: persist + hard-reset then exit")
        try:
            self.controller.persist()
        except Exception as exc:
            _log(f"persist failed: {exc}")
        try:
            apply_hard_reset(all_displays=True)
            reset_nv_color(all_displays=True)
        except Exception as exc:
            _log(f"hard_reset failed: {exc}")
        try:
            self.controller.stop_services(reset=True)
        except Exception as exc:
            _log(f"stop_services failed: {exc}")
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
        for win in (self.menu_window, self.window):
            if win is None:
                continue
            try:
                win.destroy()
            except Exception:
                pass

    def _start_tray(self) -> None:
        self.icon = FluentTrayIcon(
            APP_NAME,
            make_icon(),
            APP_NAME,
            menu=None,
            on_left=self.open_settings,
            on_right=self._show_tray_menu,
        )

        def _run_tray() -> None:
            _log("pystray.run() starting")
            try:
                assert self.icon is not None
                self.icon.run()
            except Exception:
                _log("pystray.run() crashed:\n" + traceback.format_exc())
            _log("pystray.run() exited")

        self._tray_thread = threading.Thread(target=_run_tray, name="pystray", daemon=True)
        self._tray_thread.start()

    def run(self, *, open_settings_on_start: bool = True) -> None:
        self._start_tray()

        self.menu_window, self.menu_api = create_tray_menu_window(
            self.controller,
            on_settings=self.open_settings,
            on_quit=self.quit_app,
            on_folder=self._open_folder,
            on_reset=self._hard_reset_menu,
            should_exit=lambda: self._exiting,
        )

        self.window, self.api = create_settings_window(
            self.controller,
            hidden=not open_settings_on_start,
            on_hide=self._on_settings_hidden,
            should_exit=lambda: self._exiting,
        )

        def _on_shown() -> None:
            self._gui_ready.set()
            _log("WebView2 GUI ready")

        self.window.events.shown += _on_shown

        try:
            webview.start(debug=False, icon=str(icon_ico_path()))
        finally:
            try:
                self.controller.persist()
            except Exception:
                pass
            if not self._exiting:
                self._exiting = True
                _log("webview end: hard-reset")
                try:
                    apply_hard_reset(all_displays=True)
                    reset_nv_color(all_displays=True)
                except Exception:
                    pass
                try:
                    self.controller.stop_services(reset=True)
                except Exception:
                    pass
                if self.icon is not None:
                    try:
                        self.icon.stop()
                    except Exception:
                        pass


def ensure_single_instance():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    CreateMutexW = kernel32.CreateMutexW
    CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    CreateMutexW.restype = wintypes.HANDLE
    ERROR_ALREADY_EXISTS = 183
    kernel32.SetLastError(0)
    handle = CreateMutexW(None, False, MUTEX_NAME)
    if handle and ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return handle


def main() -> int:
    mutex = ensure_single_instance()
    if mutex is None:
        _message_box(APP_NAME, f"{APP_NAME} уже запущена.\nПроверьте трей.")
        return 1

    atexit.register(lambda: (apply_hard_reset(all_displays=True), reset_nv_color(all_displays=True)))

    app = TrayApp()
    open_ui = True
    if not getattr(sys, "frozen", False):
        open_ui = not bool(app.controller.cfg.get("start_minimized_to_tray", False))

    _log(f"config_path={config_path()}")
    _log(f"open_settings_on_start={open_ui} ui=webview2")
    app.run(open_settings_on_start=open_ui)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
