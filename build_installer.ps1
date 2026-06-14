# Build the Alpha POS desktop deliverables end to end:
#   powershell -ExecutionPolicy Bypass -File build_installer.ps1
#
# Produces (in DELIVERABLES\):
#   AlphaPOS-Setup.exe     <- onedir + Inno Setup. Per-user install, AUTO-UPDATES.
#   AlphaPOS-Portable.exe  <- one-file, copy-and-run (no install, no auto-update).
#
# The build venv must have the core submodule + toolchain installed. Install core
# NON-editable (no -e): PyInstaller's module graph does not follow PEP 660 editable
# installs, so an editable core silently drops the top-level `alpha_pos_core` package
# from the bundle. This script force-reinstalls it normally below, but for a manual
# setup use:
#   pip install .\alpha_pos_core "uvicorn[standard]" channels daphne `
#               pyinstaller pywebview pythonnet Pillow tufup
# Auto-update needs the signing root: run `python tools\release.py --init` once
# (creates update_keys\ + update_repo\metadata\root.json, which the build bundles).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Prefer .venv-build, then a local .venv, then the workspace venv one level up.
$venv = @('.venv-build', '.venv', '..\.venv') |
    Where-Object { Test-Path (Join-Path $root "$_\Scripts\python.exe") } | Select-Object -First 1
if (-not $venv) { throw "No build venv found (.venv-build / .venv / ..\.venv)." }
Write-Host "Using build venv: $venv" -ForegroundColor DarkCyan
$py = Join-Path $root "$venv\Scripts\python.exe"
$pyinstaller = Join-Path $root "$venv\Scripts\pyinstaller.exe"

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1

$env:SECRET_KEY = 'build-time-secret'; $env:DEBUG = 'True'

# Core MUST be a regular (non-editable) install. PyInstaller's module graph does
# not follow PEP 660 editable installs, so an editable core bundles core.* but not
# the top-level `alpha_pos_core` package -> the frozen app ModuleNotFounds at launch
# on `from alpha_pos_core.settings_base import *`. Force a normal reinstall here so a
# clean checkout (or a dev box left on an editable core) always builds correctly.
Write-Host '== 0/4  Ensuring non-editable core install ==' -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $root 'alpha_pos_core\pyproject.toml'))) {
    throw "core submodule missing - run: git submodule update --init --recursive"
}
& $py -m pip install --quiet --no-deps --force-reinstall (Join-Path $root 'alpha_pos_core')
if ($LASTEXITCODE -ne 0) { throw "core install failed ($LASTEXITCODE)" }

Write-Host '== 1/4  Generating icon ==' -ForegroundColor Cyan
& $py 'desktop\make_icon.py'

Write-Host '== 2/4  Building onedir (auto-updating app) ==' -ForegroundColor Cyan
& $pyinstaller --noconfirm --clean 'AlphaPOS.spec'
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (onedir) failed ($LASTEXITCODE)" }

Write-Host '== 3/4  Building portable one-file ==' -ForegroundColor Cyan
& $pyinstaller --noconfirm 'AlphaPOS-onefile.spec'
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (onefile) failed ($LASTEXITCODE)" }

Write-Host '== 4/4  Compiling Setup installer (Inno Setup) ==' -ForegroundColor Cyan
if ($iscc) {
    & $iscc 'installer\AlphaPOS.iss'
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed ($LASTEXITCODE)" }
} else {
    Write-Host 'ISCC not found - skipping Setup installer (install Inno Setup 6).' -ForegroundColor Yellow
}

$deliv = Join-Path $root 'DELIVERABLES'
New-Item -ItemType Directory -Force -Path $deliv | Out-Null
if (Test-Path "$root\installer\Output\AlphaPOS-Setup.exe") {
    Copy-Item "$root\installer\Output\AlphaPOS-Setup.exe" "$deliv\AlphaPOS-Setup.exe" -Force
}
if (Test-Path "$root\dist\AlphaPOS.exe") {
    Copy-Item "$root\dist\AlphaPOS.exe" "$deliv\AlphaPOS-Portable.exe" -Force
}

Write-Host ''
Write-Host "DONE. Deliverables in $deliv :" -ForegroundColor Green
Get-ChildItem $deliv -File | Format-Table Name, @{N = 'Size'; E = { '{0:N0} MB' -f ($_.Length / 1MB) } }
