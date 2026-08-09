"""Settings window — WebView2 Fluent UI bridged to AppController."""

from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import webview

from hotkeys import format_hotkey

if TYPE_CHECKING:
    from controller import AppController


def resource_dir() -> Path:
    """Bundled resources root (PyInstaller MEIPASS) or project root."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def ui_dir() -> Path:
    return resource_dir() / "ui"


def ui_index() -> str:
    return str(ui_dir() / "index.html")


class SettingsApi:
    """
    Exposed to JS as window.pywebview.api.

    IMPORTANT: only public *methods* — any public attribute is recursively
    walked by pywebview (see util.get_functions) and will hang on
    window.native.AccessibilityObject.Bounds.Empty...
    """

    def __init__(self, controller: AppController) -> None:
        self._controller = controller
        self._selected: str | None = controller.current
        self._window: webview.Window | None = None
        self._page_ready = threading.Event()

    def _ok(self, **extra: Any) -> dict[str, Any]:
        return {"ok": True, **extra}

    def _err(self, exc: Exception) -> dict[str, Any]:
        return {"ok": False, "error": str(exc)}

    def get_state(self, selected: str | None = None) -> dict[str, Any]:
        self._page_ready.set()
        snap = self._controller.snapshot_for_ui()
        presets = dict(snap.get("presets") or {})
        if selected and selected in presets:
            self._selected = selected
        elif self._selected not in presets:
            self._selected = snap.get("current") or "Default"
        # JSON-safe plain types only
        return {
            "presets": {
                name: {
                    "brightness": float(raw.get("brightness", 0.5)),
                    "contrast": float(raw.get("contrast", 0.5)),
                    "gamma": float(raw.get("gamma", 1.0)),
                    "vibrance": int(round(float(raw.get("vibrance", 50)))),
                    "hue": int(round(float(raw.get("hue", 0)))),
                }
                for name, raw in presets.items()
                if isinstance(raw, dict)
            },
            "hotkeys": {
                str(k): format_hotkey(str(v)) if v else ""
                for k, v in (snap.get("hotkeys") or {}).items()
            },
            "current": str(snap.get("current") or "Default"),
            "selected": str(self._selected or "Default"),
            "watch": self._watch_for_ui(snap.get("watch") or {}),
            "apply_all_displays": bool(snap.get("apply_all_displays")),
            "notify_on_switch": bool(snap.get("notify_on_switch", True)),
            "ui_language": "ru" if str(snap.get("ui_language") or "en").lower().startswith("ru") else "en",
        }

    @staticmethod
    def _watch_for_ui(watch: dict[str, Any]) -> dict[str, Any]:
        rules_out: list[dict[str, Any]] = []
        for rule in watch.get("rules") or []:
            if not isinstance(rule, dict):
                continue
            procs = rule.get("process_names") or []
            if not isinstance(procs, list):
                procs = []
            rules_out.append(
                {
                    "id": str(rule.get("id") or ""),
                    "name": str(rule.get("name") or ""),
                    "enabled": bool(rule.get("enabled", True)),
                    "process_names": [str(p) for p in procs if isinstance(p, str) and p.strip()],
                    "on_start": str(rule.get("on_start") or "Default"),
                    "on_exit": str(rule.get("on_exit") or "Default"),
                }
            )
        return {
            "enabled": bool(watch.get("enabled")),
            "poll_ms": int(watch.get("poll_ms") or 1500),
            "rules": rules_out,
        }

    def select_preset(self, name: str) -> dict[str, Any]:
        if name in self._controller.presets:
            self._selected = name
        return self._ok(selected=self._selected)

    def apply(self, name: str) -> dict[str, Any]:
        try:
            self._controller.apply_named(name, reason="ui")
            self._selected = name
            return self._ok(name=name)
        except Exception as exc:
            return self._err(exc)

    def live(
        self,
        brightness: float,
        contrast: float,
        gamma: float,
        vibrance: int = 50,
        hue: int = 0,
    ) -> dict[str, Any]:
        try:
            self._controller.apply_live(
                float(brightness),
                float(contrast),
                float(gamma),
                int(vibrance),
                int(hue),
            )
            return self._ok()
        except Exception as exc:
            return self._err(exc)

    def save(
        self,
        name: str,
        brightness: float,
        contrast: float,
        gamma: float,
        hotkey: str,
        old_name: str | None = None,
        vibrance: int = 50,
        hue: int = 0,
    ) -> dict[str, Any]:
        try:
            old = old_name if old_name and old_name != name else None
            self._controller.save_preset_with_hotkey(
                name,
                float(brightness),
                float(contrast),
                float(gamma),
                hotkey or "",
                int(vibrance),
                int(hue),
                old_name=old,
            )
            self._selected = name.strip()
            return self._ok(name=self._selected)
        except Exception as exc:
            return self._err(exc)

    def new_preset(
        self,
        brightness: float = 0.5,
        contrast: float = 0.5,
        gamma: float = 1.0,
        vibrance: int = 50,
        hue: int = 0,
    ) -> dict[str, Any]:
        try:
            from config_store import DEFAULT_PRESET

            base = "Preset"
            i = 1
            while f"{base}{i}" in self._controller.presets:
                i += 1
            name = f"{base}{i}"
            d = DEFAULT_PRESET
            self._controller.save_preset_values(
                name,
                float(d["brightness"]),
                float(d["contrast"]),
                float(d["gamma"]),
                int(d["vibrance"]),
                int(d["hue"]),
            )
            self._selected = name
            return self._ok(name=name)
        except Exception as exc:
            return self._err(exc)

    def delete_preset(self, name: str) -> dict[str, Any]:
        try:
            self._controller.delete_preset(name)
            self._selected = "Default"
            return self._ok()
        except Exception as exc:
            return self._err(exc)

    def save_options(self, opts: dict[str, Any]) -> dict[str, Any]:
        try:
            self._controller.set_apply_all_displays(bool(opts.get("all_displays")))
            if "notify" in opts:
                self._controller.set_notify(bool(opts.get("notify")))
            rules_raw = opts.get("rules")
            rules = rules_raw if isinstance(rules_raw, list) else []
            poll_ms = opts.get("poll_ms")
            self._controller.set_watch_config(
                enabled=bool(opts.get("watch_enabled")),
                rules=rules,
                poll_ms=int(poll_ms) if poll_ms is not None else None,
            )
            return self._ok()
        except Exception as exc:
            return self._err(exc)

    def set_language(self, language: str) -> dict[str, Any]:
        try:
            lang = self._controller.set_ui_language(language)
            return self._ok(ui_language=lang)
        except Exception as exc:
            return self._err(exc)

    def hard_reset(self) -> dict[str, Any]:
        try:
            self._controller.hard_reset()
            self._selected = "Default"
            return self._ok()
        except Exception as exc:
            return self._err(exc)

    def export_config(self) -> dict[str, Any]:
        window = self._window
        if window is None:
            return self._err(RuntimeError("Window not ready"))
        try:
            from config_store import app_dir

            result = window.create_file_dialog(
                webview.FileDialog.SAVE,
                directory=str(app_dir()),
                save_filename="config.json",
                file_types=("JSON (*.json)",),
            )
            if not result:
                return self._ok(cancelled=True)
            path = result[0]
            if not str(path).lower().endswith(".json"):
                path = f"{path}.json"
            self._controller.export_config(path)
            return self._ok(path=str(path))
        except Exception as exc:
            return self._err(exc)

    def import_config(self) -> dict[str, Any]:
        window = self._window
        if window is None:
            return self._err(RuntimeError("Window not ready"))
        try:
            from config_store import app_dir

            result = window.create_file_dialog(
                webview.FileDialog.OPEN,
                directory=str(app_dir()),
                allow_multiple=False,
                file_types=("JSON (*.json)",),
            )
            if not result:
                return self._ok(cancelled=True)
            path = result[0]
            self._controller.import_config(path)
            self._selected = "Default"
            state = self.get_state("Default")
            return self._ok(path=str(path), **state)
        except Exception as exc:
            return self._err(exc)

    def _push_refresh(self) -> None:
        """Called from controller.on_change (any thread). Skip until page is ready."""
        if not self._page_ready.is_set():
            return
        window = self._window
        if window is None:
            return

        def _run() -> None:
            try:
                payload = self.get_state(self._selected)
                js = (
                    "window.refreshFromPython && window.refreshFromPython("
                    + json.dumps(payload)
                    + ")"
                )
                window.evaluate_js(js)
            except Exception:
                pass

        threading.Thread(target=_run, name="nvcolor-ui-refresh", daemon=True).start()


WINDOW_WIDTH = 900
WINDOW_HEIGHT = 1028
WINDOW_MIN_WIDTH = 900
WINDOW_MIN_HEIGHT = 1028


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _frame_pads(hwnd: int) -> tuple[int, int]:
    """Invisible Win11 resize-border padding (GetWindowRect − extended frame)."""
    try:
        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi
        wr = _RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(wr))
        frame = _RECT()
        hr = dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(frame), ctypes.sizeof(frame))
        if hr != 0:
            return 0, 0
        pad_x = (wr.right - wr.left) - (frame.right - frame.left)
        pad_y = (wr.bottom - wr.top) - (frame.bottom - frame.top)
        if pad_x < 0 or pad_x > 40:
            pad_x = 0
        if pad_y < 0 or pad_y > 40:
            pad_y = 0
        return int(pad_x), int(pad_y)
    except Exception:
        return 0, 0


def _force_outer_size(window: webview.Window, width: int, height: int) -> None:
    """
    Make the *visible* window frame (DWM extended bounds) exactly width×height.
    Win11 has invisible resize borders; SetWindowPos alone targets GetWindowRect,
    which is larger than what the user sees.
    """
    try:
        from ctypes import wintypes

        native = getattr(window, "native", None)
        if native is None:
            return
        hwnd = int(native.Handle.ToInt32())
        if not hwnd:
            return

        pad_x, pad_y = _frame_pads(hwnd)
        outer_w = int(width) + pad_x
        outer_h = int(height) + pad_y

        # SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE
        ctypes.windll.user32.SetWindowPos(
            wintypes.HWND(hwnd),
            None,
            0,
            0,
            outer_w,
            outer_h,
            0x0002 | 0x0004 | 0x0010,
        )
        _apply_min_size(window)
    except Exception:
        pass


def _apply_min_size(window: webview.Window) -> None:
    """Minimum visible width = WINDOW_MIN_WIDTH (plus Win11 invisible border pads)."""
    try:
        from System.Drawing import Size

        native = getattr(window, "native", None)
        if native is None:
            return
        hwnd = int(native.Handle.ToInt32())
        pad_x, pad_y = _frame_pads(hwnd)
        native.MinimumSize = Size(
            int(WINDOW_MIN_WIDTH) + pad_x,
            int(WINDOW_MIN_HEIGHT) + pad_y,
        )
    except Exception:
        pass


def _schedule_size_fixes(window: webview.Window) -> None:
    """Apply size now and again shortly after layout/DPI settle."""

    def _apply() -> None:
        _force_outer_size(window, WINDOW_WIDTH, WINDOW_HEIGHT)
        _apply_min_size(window)

    def _later(delay_ms: int) -> None:
        def _run() -> None:
            time.sleep(delay_ms / 1000.0)
            try:
                native = getattr(window, "native", None)
                if native is not None and hasattr(native, "Invoke"):
                    from System import Action

                    native.Invoke(Action(_apply))
                else:
                    _apply()
            except Exception:
                _apply()

        threading.Thread(target=_run, name="nvcolor-size", daemon=True).start()

    _apply()
    for delay in (50, 200, 500):
        _later(delay)


def create_settings_window(
    controller: AppController,
    *,
    hidden: bool = False,
    on_hide: Callable[[], None] | None = None,
    should_exit: Callable[[], bool] | None = None,
) -> tuple[webview.Window, SettingsApi]:
    """
    Create the settings WebView.

    Close button: hide to tray (cancel destroy) unless should_exit() is True.
    pywebview cancels close when a closing handler returns False.
    """
    api = SettingsApi(controller)
    window = webview.create_window(
        "NVColor",
        url=ui_index(),
        js_api=api,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT),
        background_color="#1c1c1c",
        text_select=False,
        confirm_close=False,
        hidden=hidden,
    )
    api._window = window

    def _on_shown() -> None:
        _schedule_size_fixes(window)

    window.events.shown += _on_shown
    window.events.loaded += lambda: (
        _force_outer_size(window, WINDOW_WIDTH, WINDOW_HEIGHT),
        _apply_min_size(window),
    )

    def _on_closing() -> bool | None:
        if should_exit and should_exit():
            return None  # allow destroy
        try:
            window.hide()
        except Exception:
            pass
        if on_hide:
            try:
                on_hide()
            except Exception:
                pass
        return False  # cancel destroy

    window.events.closing += _on_closing
    controller.on_change(api._push_refresh)
    return window, api
