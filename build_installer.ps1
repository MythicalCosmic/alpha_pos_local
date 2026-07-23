# Build the Alpha POS desktop deliverables end to end:
#   powershell -ExecutionPolicy Bypass -File build_installer.ps1
#
# Produces (in DELIVERABLES\):
#   AlphaPOS-Setup.exe     <- onedir + Inno Setup. Per-user install, AUTO-UPDATES.
#   AlphaPOS-Portable.exe  <- one-file, copy-and-run (no install, no auto-update).
#   AlphaPOS-Support-Connector.ps1 + pinned relay host key (no private key).
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

# Prefer .venv-build, then a local .venv, then workspace venvs one or two
# levels up (the second form is used by isolated git worktrees).
$venv = @('.venv-build', '.venv', '..\.venv', '..\..\.venv') |
    Where-Object { Test-Path (Join-Path $root "$_\Scripts\python.exe") } | Select-Object -First 1
if (-not $venv) { throw "No build venv found (.venv-build / .venv / ..\.venv / ..\..\.venv)." }
Write-Host "Using build venv: $venv" -ForegroundColor DarkCyan
$py = Join-Path $root "$venv\Scripts\python.exe"
$pyinstaller = Join-Path $root "$venv\Scripts\pyinstaller.exe"

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1

$env:SECRET_KEY = 'build-time-secret'; $env:DEBUG = 'True'

# Resolve large/trusted release inputs explicitly. A successful executable that
# silently lacks PostgreSQL or the TUF root is not a valid Alpha POS release.
$pgsql = @((Join-Path $root '_pg\pgsql'),
           (Join-Path $root '..\_pg\pgsql'),
           (Join-Path $root '..\..\_pg\pgsql')) |
         Where-Object { Test-Path $_ -PathType Container } | Select-Object -First 1
if (-not $pgsql) { throw "Embedded PostgreSQL not found at _pg/pgsql up to two workspace levels above." }
$tufRoot = @((Join-Path $root 'update_repo\metadata\root.json'),
             (Join-Path $root '..\alpha_pos_local\update_repo\metadata\root.json'),
             (Join-Path $root '..\..\alpha_pos_local\update_repo\metadata\root.json')) |
           Where-Object { Test-Path $_ -PathType Leaf } | Select-Object -First 1
if (-not $tufRoot) { throw "Trusted TUF root.json not found; refusing to build an app with updates disabled." }
$env:ALPHA_POS_PGSQL_DIR = (Resolve-Path $pgsql).Path
$env:ALPHA_POS_TUF_ROOT = (Resolve-Path $tufRoot).Path
Write-Host "Embedded PostgreSQL: $env:ALPHA_POS_PGSQL_DIR" -ForegroundColor DarkCyan
Write-Host "Trusted update root: $env:ALPHA_POS_TUF_ROOT" -ForegroundColor DarkCyan

# Keep the Python app, signed update bundle, and Windows installer on exactly
# the same version. desktop/version.py is the release source of truth; the
# numeric x.y.z check also guarantees that Inno Setup can use it for the
# executable version resource.
$versionOutput = & $py -c "from desktop.version import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0) { throw "could not read desktop version ($LASTEXITCODE)" }
$version = "$versionOutput".Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Invalid desktop version '$version' (expected numeric x.y.z)."
}
Write-Host "Building Alpha POS $version" -ForegroundColor DarkCyan

# Core MUST be a regular (non-editable) install. PyInstaller's module graph does
# not follow PEP 660 editable installs, so an editable core bundles core.* but not
# the top-level `alpha_pos_core` package -> the frozen app ModuleNotFounds at launch
# on `from alpha_pos_core.settings_base import *`. Force a normal reinstall here so a
# clean checkout (or a dev box left on an editable core) always builds correctly.
Write-Host '== 0/5  Ensuring non-editable core install ==' -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $root 'alpha_pos_core\pyproject.toml'))) {
    throw "core submodule missing - run: git submodule update --init --recursive"
}
& $py -m pip install --quiet --no-deps --force-reinstall (Join-Path $root 'alpha_pos_core')
if ($LASTEXITCODE -ne 0) { throw "core install failed ($LASTEXITCODE)" }

Write-Host '== 1/5  Precompiling desktop UI ==' -ForegroundColor Cyan
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCommand) {
    throw "Node.js is required to precompile the desktop UI. Install Node.js, then rerun the build."
}
$node = $nodeCommand.Source
& $node 'tools\compile_desktop_ui.js'
if ($LASTEXITCODE -ne 0) { throw "desktop UI compilation failed ($LASTEXITCODE)" }
& $node 'tools\compile_desktop_ui.js' '--check'
if ($LASTEXITCODE -ne 0) { throw "desktop UI bundle freshness check failed ($LASTEXITCODE)" }

Write-Host '== 2/5  Generating icon ==' -ForegroundColor Cyan
& $py 'desktop\make_icon.py'
if ($LASTEXITCODE -ne 0) { throw "icon generation failed ($LASTEXITCODE)" }

Write-Host '== 3/5  Building onedir (auto-updating app) ==' -ForegroundColor Cyan
& $pyinstaller --noconfirm --clean 'AlphaPOS.spec'
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (onedir) failed ($LASTEXITCODE)" }

Write-Host '== 4/5  Building portable one-file ==' -ForegroundColor Cyan
& $pyinstaller --noconfirm 'AlphaPOS-onefile.spec'
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (onefile) failed ($LASTEXITCODE)" }

Write-Host '== 5/5  Compiling Setup installer (Inno Setup) ==' -ForegroundColor Cyan
if ($iscc) {
    & $iscc "/DAppVersion=$version" 'installer\AlphaPOS.iss'
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed ($LASTEXITCODE)" }
} else {
    Write-Host 'ISCC not found - skipping Setup installer (install Inno Setup 6).' -ForegroundColor Yellow
}

$deliv = Join-Path $root 'DELIVERABLES'
New-Item -ItemType Directory -Force -Path $deliv | Out-Null
if ($iscc) {
    $installer = Join-Path $root "installer\Output\AlphaPOS-$version-Setup.exe"
    if (-not (Test-Path $installer)) {
        throw "Inno Setup succeeded but expected installer is missing: $installer"
    }
    Copy-Item $installer "$deliv\AlphaPOS-Setup.exe" -Force
    Copy-Item $installer "$deliv\AlphaPOS-$version-Setup.exe" -Force
}
$portable = Join-Path $root 'dist\AlphaPOS.exe'
if (-not (Test-Path $portable)) {
    throw "PyInstaller succeeded but expected portable executable is missing: $portable"
}
Copy-Item $portable "$deliv\AlphaPOS-Portable.exe" -Force
Copy-Item $portable "$deliv\AlphaPOS-$version-Portable.exe" -Force
Copy-Item (Join-Path $root 'tools\connect_support_relay.ps1') `
    "$deliv\AlphaPOS-Support-Connector.ps1" -Force
Copy-Item (Join-Path $root 'tools\support_relay_known_hosts') `
    "$deliv\AlphaPOS-Support-Relay-Known-Hosts" -Force
Copy-Item (Join-Path $root 'SUPPORT_TUNNEL_HOME_INSPECTION.md') `
    "$deliv\AlphaPOS-Support-Tunnel-Guide.md" -Force

Write-Host ''
Write-Host "DONE. Deliverables in $deliv :" -ForegroundColor Green
Get-ChildItem $deliv -File | Format-Table Name, @{N = 'Size'; E = { '{0:N0} MB' -f ($_.Length / 1MB) } }
