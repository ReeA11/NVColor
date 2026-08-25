# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve().parent

datas = [
    (str(ROOT / "nvcolor" / "ui"), "ui"),
    (str(ROOT / "nvcolor" / "assets"), "assets"),
]
binaries = []
hiddenimports = [
    "pystray._win32",
    "clr",
    "pythonnet",
    "nvcolor",
    "nvcolor.app",
    "nvcolor.controller",
    "nvcolor.config_store",
    "nvcolor.gamma_control",
    "nvcolor.hotkeys",
    "nvcolor.nvapi_color",
    "nvcolor.process_watch",
    "nvcolor.settings_webview",
    "nvcolor.tray_menu",
]
tmp_ret = collect_all("pystray")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]
tmp_ret = collect_all("PIL")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]
tmp_ret = collect_all("webview")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]


a = Analysis(
    [str(ROOT / "nvcolor" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NVColor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(ROOT / "nvcolor" / "assets" / "nvcolor.ico")],
)
