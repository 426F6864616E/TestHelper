# Builds TestHelper.exe (PyInstaller) and the installer (Inno Setup).
# Usage:  powershell -ExecutionPolicy Bypass -File installer\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

python -m pip install -q -r requirements.txt pyinstaller
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

python -m PyInstaller main.py `
    --name TestHelper `
    --noconfirm --windowed --clean `
    --icon "$root\assets\icon.ico" `
    --add-data "$root\assets;assets" `
    --add-data "$root\locales;locales" `
    --collect-data customtkinter `
    --hidden-import pystray._win32 `
    --distpath dist --workpath build --specpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found (winget install JRSoftware.InnoSetup)" }
& $iscc installer\TestHelper.iss
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }
Write-Host "Done: dist\installer"
