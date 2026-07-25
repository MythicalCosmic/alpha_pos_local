# Desktop self-update (tufup + smooth Windows handoff)

Goal: **publish a signed build → let every POS update without replacing its
business data.** Releases remain cryptographically authenticated through TUF.

| Piece | File | Role |
|-------|------|------|
| Version | `desktop/version.py` | release source of truth |
| Client | `desktop/updater.py` | async signed download and progress state |
| Swap helper | `desktop/update_helper.ps1` | bounded atomic swap, rollback and relaunch |
| Publisher | `tools/release.py` | bundles, signs and updates the repository |
| Launcher | `desktop/app.py` | background check and graceful shutdown callback |

The client is a guaranteed no-op unless it is a frozen Windows build, `tufup`
is installed, `ALPHA_POS_UPDATE_URL` is set, and both a trusted
`tuf_root/root.json` and the WPF helper are bundled. `--no-update` skips the
background metadata check.

Startup checks only; it never closes a working till by surprise. The operator
chooses **Install now**, sees live download progress, and the app releases
uvicorn, Django and embedded Postgres before the helper replaces files and
relaunches it.

## Why there is a custom Windows helper

tufup's default Windows installer starts a visible `cmd.exe` and invokes
robocopy without `/R`. Windows then defaults to one million retries. If the
still-running app holds its EXE, Python DLLs, WebView or another bundle file,
that produces the old terminal/retry loop.

Alpha POS instead provides:

- a styled progress window and no console process;
- a rendered-window handshake before the live POS is allowed to close;
- a maximum 45-second wait for the parent process;
- 12 bounded rename attempts (no unbounded copy loop);
- same-volume, near-atomic directory activation;
- preservation of Inno Setup's `unins*` files;
- rollback to the previous directory when activation fails;
- a 120-second backend-health confirmation window after launch;
- automatic rollback/relaunch of the previous version if the new process
  exits early or never becomes healthy; and
- automatic relaunch after a successful swap.

## One-time setup

### 1. Create signing keys and the repository

```powershell
pip install -r requirements-desktop.txt
python tools/release.py --init
```

This creates:

- `update_keys/`: private signing keys. Back them up offline and never publish
  them. Losing the root key requires reinstalling clients to establish trust.
- `update_repo/`: public metadata and targets served to clients.

### 2. Bundle the trust root and helper

`AlphaPOS.spec` always includes the helper and receives the trusted root from
the build script through `ALPHA_POS_TUF_ROOT`:

```python
datas += [
    ('desktop/update_helper.ps1', 'desktop'),
]
_tuf_root = os.environ.get('ALPHA_POS_TUF_ROOT')
if _tuf_root and os.path.exists(_tuf_root):
    datas += [(_tuf_root, 'tuf_root')]
```

### 3. Configure the update repository URL

Set this in the desktop Configuration page / `.env`:

```text
ALPHA_POS_UPDATE_URL=https://control.<server-ip>.nip.io/updates
```

The Control Center host serves `metadata/` and `targets/` under that path.

## Each release

```powershell
# 1. Bump desktop/version.py
# 2. Build the onedir app and installer
powershell -ExecutionPolicy Bypass -File build_installer.ps1

# 3. Sign the onedir bundle
..\.venv\Scripts\python.exe tools/release.py --publish --bundle dist/AlphaPOS

# 4. Promote update_repo/ to /srv/alpha_pos_updates/ on the control host
```

Upload and hash-check the new target archive in a staging directory first.
Promote the target, then `targets.json`, then `snapshot.json`, and
`timestamp.json` **last**.  Do not copy the whole repository in arbitrary
filesystem order: publishing metadata before its referenced archive can make a
valid update temporarily impossible to download.  `root.json` is unchanged for
an ordinary release and should not be replaced.

On the next launch, each POS refreshes signed metadata. The Updates page offers
the signed version. **Install now** downloads it with live byte progress,
verifies and extracts it, closes Alpha POS safely, swaps it, and opens the new
version automatically.

## First rollout from the legacy updater

Builds predating this helper still contain tufup's old cmd/robocopy installer.
They cannot acquire the replacement logic until one update has completed. Use
the new Setup installer for that one in-place upgrade. It keeps all business
data under `%LOCALAPPDATA%\AlphaPOS`; every later release uses the smooth flow.

If the old Updates button must be used for this first hop, close the old Alpha
POS window when its legacy terminal appears so it releases the install files.
The Setup installer is the preferred and predictable migration path.

## Health, rollback and cleanup

`updater.py` writes `update_pending.flag` only after download, signature
verification and extraction. The new process records success only when the
marker version exactly matches its running version **and** migrations/database
startup have progressed far enough for the POS backend to bind successfully.
It then deletes the old rollback directory asynchronously. If an old or broken
process starts instead, it preserves both the marker and rollback directory and
surfaces the mismatch; it never destroys the recovery copy.

Signed metadata refresh is mandatory. A network failure or invalid/unsigned
metadata is shown as an update error and can be retried; it is never reported
as "up to date" and never reaches the install helper.

The helper restores the previous directory immediately if activation fails. It
also removes the pending marker so reopening the previous app cannot be
misreported as a successful update. After launching the new executable, it
keeps the rollback copy until the new app confirms a successfully bound POS
backend. A crash or two-minute readiness timeout stops the failed process tree,
restores that copy, and reopens the previous version. The helper log is stored
at:

```text
%LOCALAPPDATA%\AlphaPOS\update\update-helper.log
```

To ship old behavior again, publish it under a higher semantic version; TUF
correctly prevents downgrade metadata from silently replacing a newer build.

## Safe helper smoke test

The helper has a release-only headless mode for disposable same-volume folders.
The automated success, failure, rollback and no-console contracts run with:

```powershell
$env:DEBUG='True'; $env:SECRET_KEY='test'
..\.venv\Scripts\python.exe -m pytest test_updater_flow.py -q
```

For a manual dummy run, create sibling `current` and `staged` directories under
`$env:TEMP`, put harmless files in them, then run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop\update_helper.ps1 `
  -ParentPid 2147483646 -Source "$env:TEMP\AlphaPOS-sim\staged" `
  -Destination "$env:TEMP\AlphaPOS-sim\current" -Version 9.9.9 `
  -MarkerPath "$env:TEMP\AlphaPOS-sim\pending.flag" `
  -LogPath "$env:TEMP\AlphaPOS-sim\helper.log" -Headless -SkipRelaunch
```

Add `-TestFailAfterBackup` to force failure after moving `current`. It must
return exit code 1, restore `current`, and remove the pending marker. Never point
a simulation at the real install directory.

## Caveats

- Updates require the onedir PyInstaller layout. The one-file portable cannot
  update itself in place.
- Success and forced rollback are tested against disposable Windows folders;
  still canary one hosted signed update before a fleet rollout.
- This implementation targets tufup 0.10. Recheck `Client` and `Repository`
  calls whenever the dependency is upgraded.
