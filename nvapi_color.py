"""NVIDIA Digital Vibrance + Hue via undocumented NVAPI QueryInterface IDs.

Matches NVIDIA Control Panel Desktop Color Settings:
  - Digital Vibrance: 0..100 (default usually 50)
  - Hue: 0..360 degrees (default usually 0)

Requires NVIDIA driver / nvapi64.dll. Gracefully no-ops if unavailable.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import CFUNCTYPE, POINTER, byref, c_int, c_uint, c_void_p
from dataclasses import dataclass
from typing import Callable


NVAPI_OK = 0
NVAPI_END_ENUMERATION = -7

# QueryInterface IDs (community / NvAPIWrapper)
_ID_INITIALIZE = 0x0150E828
_ID_UNLOAD = 0xD22BDD7E
_ID_ENUM_NVIDIA_DISPLAY_HANDLE = 0x9ABDD40D
_ID_GET_DVC_INFO = 0x4085DE45
_ID_GET_DVC_INFO_EX = 0x0E45002D
_ID_SET_DVC_LEVEL = 0x172409B4
_ID_SET_DVC_LEVEL_EX = 0x4A82C2B1
_ID_GET_HUE_INFO = 0x95B64341
_ID_SET_HUE_ANGLE = 0xF5A0F22C

DEFAULT_VIBRANCE = 50
DEFAULT_HUE = 0


class NV_DISPLAY_DVC_INFO(ctypes.Structure):
    _fields_ = [
        ("version", c_uint),
        ("currentLevel", c_uint),
        ("minLevel", c_uint),
        ("maxLevel", c_uint),
    ]


class NV_DISPLAY_DVC_INFO_EX(ctypes.Structure):
    _fields_ = [
        ("version", c_uint),
        ("currentLevel", c_int),
        ("minLevel", c_int),
        ("maxLevel", c_int),
        ("defaultLevel", c_int),
    ]


class NV_DISPLAY_HUE_INFO(ctypes.Structure):
    _fields_ = [
        ("version", c_uint),
        ("currentHueAngle", c_uint),
        ("defaultHueAngle", c_uint),
    ]


def _make_version(size: int, ver: int = 1) -> int:
    return size | (ver << 16)


@dataclass(frozen=True)
class DvcInfo:
    current: int
    minimum: int
    maximum: int
    default: int


@dataclass(frozen=True)
class HueInfo:
    current: int
    default: int


class NvApiColor:
    """Process-wide NVAPI session for vibrance / hue."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ok = False
        self._dll = None
        self._Initialize: Callable[[], int] | None = None
        self._Unload: Callable[[], int] | None = None
        self._EnumDisplay: Callable[[int, ctypes.c_void_p], int] | None = None
        self._GetDvc: Callable[..., int] | None = None
        self._GetDvcEx: Callable[..., int] | None = None
        self._SetDvc: Callable[..., int] | None = None
        self._SetDvcEx: Callable[..., int] | None = None
        self._GetHue: Callable[..., int] | None = None
        self._SetHue: Callable[..., int] | None = None
        self._init()

    @property
    def available(self) -> bool:
        return self._ok

    def _query(self, iid: int):
        assert self._dll is not None
        fn = self._dll.nvapi_QueryInterface
        fn.restype = c_void_p
        fn.argtypes = [c_uint]
        ptr = fn(iid)
        return ptr

    def _bind(self, iid: int, prototype):
        ptr = self._query(iid)
        if not ptr:
            return None
        return prototype(ptr)

    def _init(self) -> None:
        dll_name = "nvapi64.dll" if sys.maxsize > 2**32 else "nvapi.dll"
        try:
            self._dll = ctypes.WinDLL(dll_name)
        except OSError:
            print(f"[NVColor] {dll_name} not found — vibrance/hue disabled", flush=True)
            return

        try:
            self._Initialize = self._bind(_ID_INITIALIZE, CFUNCTYPE(c_int))
            self._Unload = self._bind(_ID_UNLOAD, CFUNCTYPE(c_int))
            self._EnumDisplay = self._bind(
                _ID_ENUM_NVIDIA_DISPLAY_HANDLE,
                CFUNCTYPE(c_int, c_int, POINTER(c_void_p)),
            )
            self._GetDvc = self._bind(
                _ID_GET_DVC_INFO,
                CFUNCTYPE(c_int, c_void_p, c_uint, POINTER(NV_DISPLAY_DVC_INFO)),
            )
            self._GetDvcEx = self._bind(
                _ID_GET_DVC_INFO_EX,
                CFUNCTYPE(c_int, c_void_p, c_uint, POINTER(NV_DISPLAY_DVC_INFO_EX)),
            )
            self._SetDvc = self._bind(
                _ID_SET_DVC_LEVEL,
                CFUNCTYPE(c_int, c_void_p, c_uint, c_int),
            )
            self._SetDvcEx = self._bind(
                _ID_SET_DVC_LEVEL_EX,
                CFUNCTYPE(c_int, c_void_p, c_uint, POINTER(NV_DISPLAY_DVC_INFO_EX)),
            )
            self._GetHue = self._bind(
                _ID_GET_HUE_INFO,
                CFUNCTYPE(c_int, c_void_p, c_uint, POINTER(NV_DISPLAY_HUE_INFO)),
            )
            self._SetHue = self._bind(
                _ID_SET_HUE_ANGLE,
                CFUNCTYPE(c_int, c_void_p, c_uint, c_uint),
            )
        except Exception as exc:
            print(f"[NVColor] NVAPI bind failed: {exc}", flush=True)
            return

        if not self._Initialize or not self._EnumDisplay:
            print("[NVColor] NVAPI QueryInterface failed", flush=True)
            return

        status = self._Initialize()
        if status != NVAPI_OK:
            print(f"[NVColor] NvAPI_Initialize failed ({status})", flush=True)
            return

        self._ok = True
        print("[NVColor] NVAPI ready (Digital Vibrance / Hue)", flush=True)

    def close(self) -> None:
        with self._lock:
            if self._ok and self._Unload:
                try:
                    self._Unload()
                except Exception:
                    pass
            self._ok = False

    def _handles(self, all_displays: bool) -> list[c_void_p]:
        if not self._ok or not self._EnumDisplay:
            return []
        handles: list[c_void_p] = []
        for index in range(16):
            handle = c_void_p()
            status = self._EnumDisplay(index, byref(handle))
            if status == NVAPI_END_ENUMERATION:
                break
            if status != NVAPI_OK or not handle.value:
                continue
            handles.append(handle)
            if not all_displays:
                break
        return handles

    def get_dvc(self, handle: c_void_p) -> DvcInfo | None:
        if self._GetDvcEx:
            info = NV_DISPLAY_DVC_INFO_EX()
            info.version = _make_version(ctypes.sizeof(NV_DISPLAY_DVC_INFO_EX))
            status = self._GetDvcEx(handle, 0, byref(info))
            if status == NVAPI_OK:
                return DvcInfo(
                    current=int(info.currentLevel),
                    minimum=int(info.minLevel),
                    maximum=int(info.maxLevel),
                    default=int(info.defaultLevel),
                )
        if self._GetDvc:
            info = NV_DISPLAY_DVC_INFO()
            info.version = _make_version(ctypes.sizeof(NV_DISPLAY_DVC_INFO))
            status = self._GetDvc(handle, 0, byref(info))
            if status == NVAPI_OK:
                return DvcInfo(
                    current=int(info.currentLevel),
                    minimum=int(info.minLevel),
                    maximum=int(info.maxLevel),
                    default=DEFAULT_VIBRANCE,
                )
        return None

    def get_hue(self, handle: c_void_p) -> HueInfo | None:
        if not self._GetHue:
            return None
        info = NV_DISPLAY_HUE_INFO()
        info.version = _make_version(ctypes.sizeof(NV_DISPLAY_HUE_INFO))
        status = self._GetHue(handle, 0, byref(info))
        if status != NVAPI_OK:
            return None
        return HueInfo(current=int(info.currentHueAngle), default=int(info.defaultHueAngle))

    def set_dvc(self, handle: c_void_p, level: int) -> bool:
        level = int(level)
        info = self.get_dvc(handle)
        if info is not None:
            level = max(info.minimum, min(info.maximum, level))

        if self._SetDvcEx:
            payload = NV_DISPLAY_DVC_INFO_EX()
            payload.version = _make_version(ctypes.sizeof(NV_DISPLAY_DVC_INFO_EX))
            payload.currentLevel = level
            if info is not None:
                payload.minLevel = info.minimum
                payload.maxLevel = info.maximum
                payload.defaultLevel = info.default
            status = self._SetDvcEx(handle, 0, byref(payload))
            if status == NVAPI_OK:
                return True

        if self._SetDvc:
            status = self._SetDvc(handle, 0, level)
            return status == NVAPI_OK
        return False

    def set_hue(self, handle: c_void_p, angle: int) -> bool:
        if not self._SetHue:
            return False
        angle = int(angle) % 361
        if angle > 360:
            angle = 360
        status = self._SetHue(handle, 0, c_uint(angle))
        return status == NVAPI_OK

    def apply(self, vibrance: int, hue: int, *, all_displays: bool = False) -> list[str]:
        """Apply Digital Vibrance + Hue. Returns list of applied display indices."""
        with self._lock:
            if not self._ok:
                return []
            applied: list[str] = []
            for i, handle in enumerate(self._handles(all_displays)):
                ok_v = self.set_dvc(handle, vibrance)
                ok_h = self.set_hue(handle, hue)
                if ok_v or ok_h:
                    applied.append(f"nv-dpy-{i}")
            return applied

    def reset(self, *, all_displays: bool = True) -> list[str]:
        """Reset vibrance/hue to driver defaults per display."""
        with self._lock:
            if not self._ok:
                return []
            applied: list[str] = []
            for i, handle in enumerate(self._handles(all_displays)):
                dvc = self.get_dvc(handle)
                hue = self.get_hue(handle)
                v = dvc.default if dvc else DEFAULT_VIBRANCE
                h = hue.default if hue else DEFAULT_HUE
                ok_v = self.set_dvc(handle, v)
                ok_h = self.set_hue(handle, h)
                if ok_v or ok_h:
                    applied.append(f"nv-dpy-{i}")
            return applied


_api: NvApiColor | None = None
_api_lock = threading.Lock()


def get_nvapi() -> NvApiColor:
    global _api
    with _api_lock:
        if _api is None:
            _api = NvApiColor()
        return _api


def apply_nv_color(vibrance: int, hue: int, *, all_displays: bool = False) -> list[str]:
    return get_nvapi().apply(int(vibrance), int(hue), all_displays=all_displays)


def reset_nv_color(*, all_displays: bool = True) -> list[str]:
    return get_nvapi().reset(all_displays=all_displays)


def clamp_vibrance(value: float | int) -> int:
    return max(0, min(100, int(round(float(value)))))


def clamp_hue(value: float | int) -> int:
    v = int(round(float(value)))
    if v < 0:
        return 0
    if v > 360:
        return 360
    return v
