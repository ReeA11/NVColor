# Build portable NVColor.exe (WebView2 UI + pystray)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name NVColor `
    --icon "assets\nvcolor.ico" `
    --add-data "ui;ui" `
    --add-data "assets;assets" `
    --collect-all pystray `
    --collect-all PIL `
    --collect-all webview `
    --hidden-import pystray._win32 `
    --hidden-import clr `
    --hidden-import pythonnet `
    nvcolor.py

Copy-Item -Force .\config.json .\dist\config.json

.\.venv\Scripts\python.exe -c @"
import json
from pathlib import Path
p = Path('dist/config.json')
cfg = json.loads(p.read_text(encoding='utf-8'))
cfg['start_minimized_to_tray'] = False
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print('dist config ok')
"@

Write-Host ""
Write-Host "Done: $PSScriptRoot\dist\NVColor.exe"
Write-Host "Note: WebView2 Runtime must be installed on the target PC."
