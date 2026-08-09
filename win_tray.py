"""Reliable Windows system-tray icon via Shell_NotifyIcon (no pystray)."""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

# ctypes.wintypes lacks HCURSOR on some Python builds
if not hasattr(wintypes, "HCURSOR"):
    wintypes.HCURSOR = wintypes.HANDLE

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# ---- constants ----
WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 1
WM_NULL = 0x0000

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010
NIF_SHOWTIP = 0x00000080
NIIF_INFO = 0x00000001

IDF_IDI_APPLICATION = 32512
CW_USEDEFAULT = 0x80000000
WS_OVERLAPPED = 0x00000000
HWND_MESSAGE = -3

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002

LR_DEFAULTSIZE = 0x00000040
LR_SHARED = 0x00008000
IMAGE_ICON = 1


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HCURSOR),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
        ("lPrivate", wintypes.DWORD),
    ]


DefWindowProcW = user32.DefWindowProcW
DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
DefWindowProcW.restype = ctypes.c_long


def _load_app_icon() -> wintypes.HICON:
    # IDI_APPLICATION as MAKEINTRESOURCE
    return user32.LoadIconW(None, ctypes.cast(IDF_IDI_APPLICATION, wintypes.LPCWSTR))


class WinTray:
    """
    System tray icon on its own Win32 message thread.

    Menu actions are marshalled to the Tk thread via `marshal(cb)`.
    """

    def __init__(
        self,
        tooltip: str,
        marshal: Callable[[Callable[[], None]], None],
        on_open: Callable[[], None],
        on_quit: Callable[[], None],
        menu_builder: Callable[[], list[tuple[str, Callable[[], None] | None]]],
    ) -> None:
        self.tooltip = tooltip[:127]
        self.marshal = marshal
        self.on_open = on_open
        self.on_quit = on_quit
        self.menu_builder = menu_builder

        self._thread: threading.Thread | None = None
        self._hwnd: int = 0
        self._nid: NOTIFYICONDATAW | None = None
        self._icon: wintypes.HICON = _load_app_icon()
        self._ready = threading.Event()
        self._error: Exception | None = None
        self._wndproc = None  # keep ref
        self._alive = False

    @property
    def ready(self) -> bool:
        return self._ready.is_set() and self._alive

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            self.show()
            return
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="WinTray", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise TimeoutError("WinTray failed to start")
        if self._error:
            raise self._error

    def stop(self) -> None:
        hwnd = self._hwnd
        if hwnd:
            user32.PostMessageW(hwnd, WM_DESTROY, 0, 0)
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None
        self._hwnd = 0
        self._alive = False

    def show(self) -> None:
        if self._nid and self._hwnd:
            self._nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))
            # Re-add if modify failed (icon was lost)
            if not shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid)):
                shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid))

    def notify(self, title: str, message: str) -> None:
        if not self._nid or not self._hwnd:
            return
        self._nid.uFlags = NIF_INFO | NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
        self._nid.szInfoTitle = title[:63]
        self._nid.szInfo = message[:255]
        self._nid.dwInfoFlags = NIIF_INFO
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))

    def _run(self) -> None:
        try:
            h_instance = kernel32.GetModuleHandleW(None)
            # Unique class per process — avoids ERROR_CLASS_ALREADY_EXISTS leftovers
            class_name = f"NVColorTrayClass_{kernel32.GetCurrentProcessId()}"

            @WNDPROC
            def wnd_proc(hwnd, msg, wparam, lparam):
                if msg == WM_TRAYICON:
                    if lparam in (WM_LBUTTONUP,):
                        self.marshal(self.on_open)
                    elif lparam in (WM_RBUTTONUP,):
                        self._popup_menu(hwnd)
                    return 0
                if msg == WM_DESTROY:
                    self._remove_icon()
                    user32.PostQuitMessage(0)
                    return 0
                return DefWindowProcW(hwnd, msg, wparam, lparam)

            self._wndproc = wnd_proc  # prevent GC of callback

            wc = WNDCLASSW()
            wc.lpfnWndProc = wnd_proc
            wc.hInstance = h_instance
            wc.lpszClassName = class_name
            atom = user32.RegisterClassW(ctypes.byref(wc))
            if not atom:
                err = ctypes.get_last_error()
                if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS
                    raise OSError(err, "RegisterClassW failed")

            parent = wintypes.HWND(HWND_MESSAGE)
            hwnd = user32.CreateWindowExW(
                0,
                class_name,
                "NVColorTray",
                WS_OVERLAPPED,
                0,
                0,
                0,
                0,
                parent,
                None,
                h_instance,
                None,
            )
            if not hwnd:
                raise OSError(ctypes.get_last_error(), "CreateWindowExW failed")
            self._hwnd = int(hwnd)

            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = hwnd
            nid.uID = 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
            nid.uCallbackMessage = WM_TRAYICON
            nid.hIcon = self._icon
            nid.szTip = self.tooltip
            ctypes.set_last_error(0)
            if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                raise OSError(ctypes.get_last_error(), "Shell_NotifyIcon NIM_ADD failed")
            # Prefer modern tray behavior on Win10/11
            try:
                nid.uVersion = 4
                shell32.Shell_NotifyIconW(0x00000004, ctypes.byref(nid))  # NIM_SETVERSION
            except Exception:
                pass
            self._nid = nid
            self._alive = True
            self._ready.set()

            msg = MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self._error = exc
            self._ready.set()
        finally:
            self._remove_icon()
            self._alive = False

    def _remove_icon(self) -> None:
        if self._nid and self._hwnd:
            try:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            except Exception:
                pass
        self._nid = None

    def _popup_menu(self, hwnd) -> None:
        menu = user32.CreatePopupMenu()
        # IDs: 1000+ map into actions list
        actions: list[Callable[[], None] | None] = []
        items = self.menu_builder()
        cmd_id = 1000
        for label, cb in items:
            if label == "--":
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                continue
            user32.AppendMenuW(menu, MF_STRING, cmd_id, label)
            actions.append(cb)
            cmd_id += 1

        user32.SetForegroundWindow(hwnd)
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        chosen = user32.TrackPopupMenu(
            menu,
            TPM_RETURNCMD | TPM_RIGHTBUTTON,
            pt.x,
            pt.y,
            0,
            hwnd,
            None,
        )
        user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)

        if chosen and 1000 <= chosen < 1000 + len(actions):
            cb = actions[chosen - 1000]
            if cb is not None:
                self.marshal(cb)
