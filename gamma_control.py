"""Gamma / brightness / contrast via Win32 SetDeviceGammaRamp.

Uses the same LUT formula as WindowsDisplayAPI / similar NV color tools
(brightness & contrast centered at 0.5, gamma default 1.0).

Important: some NVIDIA drivers effectively compose successive
SetDeviceGammaRamp calls. Every preset switch therefore:
  1) restores the captured baseline (or identity) ramp
  2) applies the new absolute LUT
so hotkeys replace the game profile instead of stacking on it.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterable

gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

CreateDCW = gdi32.CreateDCW
CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPVOID]
CreateDCW.restype = wintypes.HDC

DeleteDC = gdi32.DeleteDC
DeleteDC.argtypes = [wintypes.HDC]
DeleteDC.restype = wintypes.BOOL

SetDeviceGammaRamp = gdi32.SetDeviceGammaRamp
SetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]
SetDeviceGammaRamp.restype = wintypes.BOOL

GetDeviceGammaRamp = gdi32.GetDeviceGammaRamp
GetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]
GetDeviceGammaRamp.restype = wintypes.BOOL

EnumDisplayDevicesW = user32.EnumDisplayDevicesW


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


DISPLAY_DEVICE_ACTIVE = 0x00000001
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004

RampArray = ctypes.c_ushort * 256
RampBuffer = RampArray * 3  # R, G, B

# Per-device ramp captured before this process changes anything.
_baselines: dict[str, RampBuffer] = {}


@dataclass(frozen=True)
class ColorPreset:
    name: str
    brightness: float = 0.5
    contrast: float = 0.5
    gamma: float = 1.0

    def clamp(self) -> "ColorPreset":
        return ColorPreset(
            name=self.name,
            brightness=min(max(self.brightness, 0.0), 1.0),
            contrast=min(max(self.contrast, 0.0), 1.0),
            gamma=min(max(self.gamma, 0.4), 2.8),
        )

    @property
    def is_neutral(self) -> bool:
        p = self.clamp()
        return (
            abs(p.brightness - 0.5) < 1e-6
            and abs(p.contrast - 0.5) < 1e-6
            and abs(p.gamma - 1.0) < 1e-6
        )


def calculate_lut(brightness: float = 0.5, contrast: float = 0.5, gamma: float = 1.0) -> list[int]:
    """Mirror of WindowsDisplayAPI.DisplayGammaRamp.CalculateLUT."""
    gamma = min(max(gamma, 0.4), 2.8)
    contrast = (min(max(contrast, 0.0), 1.0) - 0.5) * 2.0
    brightness = (min(max(brightness, 0.0), 1.0) - 0.5) * 2.0

    offset = contrast * -25.4 if contrast > 0 else contrast * -32.0
    data_points = 256
    range_ = (data_points - 1) + offset * 2
    offset += brightness * (range_ / 5.0)

    result: list[int] = []
    for i in range(data_points):
        factor = (i + offset) / range_ if range_ != 0 else 0.0
        if factor < 0:
            factor = 0.0
        factor = factor ** (1.0 / gamma)
        factor = min(max(factor, 0.0), 1.0)
        result.append(int(round(factor * 65535)))
    return result


def identity_ramp() -> RampBuffer:
    """Linear 0..65535 ramp (hard reset for drivers that compose LUTs)."""
    buf = RampBuffer()
    for channel in range(3):
        for i in range(256):
            buf[channel][i] = int(round(i * 65535 / 255))
    return buf


def build_ramp(preset: ColorPreset) -> RampBuffer:
    p = preset.clamp()
    lut = calculate_lut(p.brightness, p.contrast, p.gamma)
    buf = RampBuffer()
    for channel in range(3):
        for i, value in enumerate(lut):
            buf[channel][i] = value
    return buf


def clone_ramp(src: RampBuffer) -> RampBuffer:
    dst = RampBuffer()
    for channel in range(3):
        for i in range(256):
            dst[channel][i] = src[channel][i]
    return dst


def list_display_devices(active_only: bool = True) -> list[tuple[str, str, bool]]:
    """Return (device_name, friendly_name, is_primary)."""
    devices: list[tuple[str, str, bool]] = []
    i = 0
    while True:
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if not EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
            break
        i += 1
        if active_only and not (dd.StateFlags & DISPLAY_DEVICE_ACTIVE):
            continue
        if not dd.DeviceName:
            continue
        is_primary = bool(dd.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE)
        devices.append((dd.DeviceName, dd.DeviceString, is_primary))
    return devices


def _target_devices(all_displays: bool) -> list[str]:
    devices = list_display_devices(active_only=True)
    if not devices:
        return []
    if all_displays:
        return [d[0] for d in devices]
    primary = [d[0] for d in devices if d[2]]
    return primary or [devices[0][0]]


def _open_dc(device_name: str | None) -> wintypes.HDC:
    if device_name:
        return CreateDCW("DISPLAY", device_name, None, None)
    return CreateDCW("DISPLAY", None, None, None)


def _get_ramp(device_name: str | None) -> RampBuffer | None:
    hdc = _open_dc(device_name)
    if not hdc:
        return None
    try:
        buf = RampBuffer()
        if not GetDeviceGammaRamp(hdc, ctypes.byref(buf)):
            return None
        return buf
    finally:
        DeleteDC(hdc)


def _set_ramp(device_name: str | None, ramp: RampBuffer) -> bool:
    hdc = _open_dc(device_name)
    if not hdc:
        return False
    try:
        # Pass a fresh buffer — some drivers are picky about pointer reuse.
        payload = clone_ramp(ramp)
        return bool(SetDeviceGammaRamp(hdc, ctypes.byref(payload)))
    finally:
        DeleteDC(hdc)


def capture_baselines(all_displays: bool = False) -> list[str]:
    """Snapshot current ramps before we change anything. Call once at startup."""
    global _baselines
    _baselines = {}
    captured: list[str] = []
    targets = _target_devices(all_displays)
    if not targets:
        ramp = _get_ramp(None)
        if ramp is not None:
            _baselines["(default)"] = clone_ramp(ramp)
            captured.append("(default)")
        return captured

    for device_name in targets:
        ramp = _get_ramp(device_name)
        if ramp is not None:
            _baselines[device_name] = clone_ramp(ramp)
            captured.append(device_name)
    return captured


def _clear_device(device_name: str | None) -> bool:
    """Force linear identity LUT (clears stacked NVIDIA software ramps)."""
    return _set_ramp(device_name, identity_ramp())


def apply_preset(preset: ColorPreset, all_displays: bool = False) -> list[str]:
    """Apply preset as a full replace: identity clear → absolute LUT.

    Default / neutral always means calculated 0.5 / 0.5 / 1.0 after a hard
    identity wipe — never the session baseline (baseline can be a leftover
    dark ramp from a previous run).
    """
    applied: list[str] = []
    targets = _target_devices(all_displays)
    targets_opt: list[str | None] = list(targets) if targets else [None]

    # Always bake an absolute curve (Default included).
    ramp = build_ramp(preset)

    for device_name in targets_opt:
        _clear_device(device_name)
        time.sleep(0.03)
        if _set_ramp(device_name, ramp):
            applied.append(device_name or "(default)")
        else:
            # Retry once after another identity wipe
            _clear_device(device_name)
            time.sleep(0.03)
            if _set_ramp(device_name, ramp):
                applied.append(device_name or "(default)")

    return applied


def hard_reset(all_displays: bool = True) -> list[str]:
    """Wipe to identity, then apply true neutral 0.5/0.5/1.0 on all targets."""
    applied: list[str] = []
    targets = _target_devices(all_displays)
    # If apply_all_displays was false during capture, still try every active
    # device on hard reset so a stuck secondary monitor is cleared too.
    if all_displays:
        targets = [d[0] for d in list_display_devices(active_only=True)] or targets
    targets_opt: list[str | None] = list(targets) if targets else [None]

    neutral = build_ramp(ColorPreset("Default", 0.5, 0.5, 1.0))
    for device_name in targets_opt:
        _clear_device(device_name)
        time.sleep(0.03)
        _clear_device(device_name)  # second wipe — NVIDIA compose quirks
        time.sleep(0.03)
        if _set_ramp(device_name, neutral):
            applied.append(device_name or "(default)")
    return applied


def restore_baselines(all_displays: bool = False) -> list[str]:
    """Restore ramps captured at process start (may be non-neutral!)."""
    applied: list[str] = []
    targets = _target_devices(all_displays)
    targets_opt: list[str | None] = list(targets) if targets else [None]
    for device_name in targets_opt:
        key = device_name or "(default)"
        baseline = _baselines.get(key)
        _clear_device(device_name)
        time.sleep(0.02)
        if baseline is not None:
            if _set_ramp(device_name, baseline):
                applied.append(key)
        else:
            if _set_ramp(device_name, build_ramp(ColorPreset("Default"))):
                applied.append(key)
    return applied
