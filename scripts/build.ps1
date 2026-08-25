# Build portable NVColor.exe (WebView2 UI + pystray)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe -m PyInstaller `
    --noconfirm `
    --clean `
    .\scripts\NVColor.spec

if (Test-Path .\config.json) {
    Copy-Item -Force .\config.json .\dist\config.json
} elseif (Test-Path .\config\example.json) {
    Copy-Item -Force .\config\example.json .\dist\config.json
}

.\.venv\Scripts\python.exe -c @"
import json
from pathlib import Path
p = Path('dist/config.json')
if p.is_file():
    cfg = json.loads(p.read_text(encoding='utf-8'))
    cfg['start_minimized_to_tray'] = False
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('dist config ok')
"@

Write-Host ""
Write-Host "Done: $PWD\dist\NVColor.exe"
Write-Host "Note: WebView2 Runtime must be installed on the target PC."
