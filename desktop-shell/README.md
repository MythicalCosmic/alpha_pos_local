# Alpha POS desktop shell (Tauri 2)

`AlphaPOS.exe` owns the native window, the single-instance lock, the splash /
update loader and the windowless Python backend. The POS itself stays in
Python (`desktop/backend_main.py`, built by `AlphaPOSBackend.spec`).

```
%LOCALAPPDATA%\Programs\AlphaPOS\
  AlphaPOS.exe                   this shell
  backend\AlphaPOSBackend.exe    PyInstaller onedir, console build, spawned hidden
  bin\alphapos-update-guard.exe  installer / rollback guard (planned)
  uninstall.exe                  NSIS
Data (unchanged): %LOCALAPPDATA%\AlphaPOS\  (.env, pgdata, logs, update\, run\)
```

## Build (Linux host, cross-compiled)

```sh
docker build -t alphapos-tauri-build:dev desktop-shell/build
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e CARGO_HOME=/cargo-home -e CARGO_TARGET_DIR=/work/target \
  -e XWIN_CACHE_DIR=/xwin-cache -e XWIN_ACCEPT_LICENSE=1 \
  -e PATH=/usr/local/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  -e RUSTUP_HOME=/usr/local/rustup \
  -v "$PWD/desktop-shell:/work" -v <cache>/cargo-home:/cargo-home -v <cache>/xwin:/xwin-cache \
  -w /work alphapos-tauri-build:dev \
  cargo tauri build --runner cargo-xwin --target x86_64-pc-windows-msvc --bundles nsis
```

Unit tests for the platform-neutral decisions: `cargo test -p alphapos-shell-core`
in the same image. Keep versions in sync with `python tools/sync_version.py`
(`desktop/version.py` is the single source).

Toolchain resolved on 2026-09-16: rustc 1.98.1, cargo-xwin 0.23.1, tauri-cli
2.11.4 (tauri-bundler 2.9.4), NSIS 3.08. The bundled portable PostgreSQL used by
the backend is 16.6.

## Backend contract

- Spawned as `AlphaPOSBackend.exe --parent-pid <shell pid> --ready-file <DATA\run\backend-<pid>.json>`
  with `ALPHAPOS_CONTROL_TOKEN` (removed from the backend's environment on read),
  `CREATE_NO_WINDOW`, cwd = data dir, stdout/stderr → `logs\backend-console.log`.
- The child is assigned to a Job Object with `KILL_ON_JOB_CLOSE`, so the whole
  tree (including `postgres.exe`, which `pg_ctl` detaches) dies with the shell.
- Ready file: `{port, pid, version}` written atomically once the control server
  binds on a free loopback port.
- `GET /lifecycle` (token header) → `booting | database | migrating | serving | stopping | error`.
- `POST /lifecycle/shutdown` → bounded stop (backend budget 25 s, hard exit 32 s);
  the shell terminates the job after 35 s.
- Panel calls go through the `backend_call` command → `POST /api/<method>`.

## NSIS findings (tauri-bundler 2.9.4 template)

- `installMode: currentUser` defaults `$INSTDIR` to `$LOCALAPPDATA\<productName>`
  (`%LOCALAPPDATA%\Alpha POS`). The default only applies while `$INSTDIR` is the
  placeholder, so `/D=<dir>` (last argument, unquoted) wins, and later installs
  reuse the registered location (`RestorePreviousInstallLocation`). The guard
  and the bridge adoption must pass `/D=%LOCALAPPDATA%\Programs\AlphaPOS`.
- `/P` = passive (progress only, auto-close), `/UPDATE` = update mode (auto-close,
  also passed to the old uninstaller), `/R` restarts the app via
  `nsis_tauri_utils::RunAsUser` with `/ARGS`. The guard does **not** pass `/R`;
  it launches the new shell itself to watch its health.
- The uninstaller only deletes `$APPDATA\<identifier>` and `$LOCALAPPDATA\<identifier>`
  when its checkbox is ticked. The identifier is `uz.alphapos.desktop`, so the
  POS data in `%LOCALAPPDATA%\AlphaPOS` is never touched. Never change the
  identifier to `AlphaPOS`.
- Hooks available: `NSIS_HOOK_PREINSTALL`, `NSIS_HOOK_POSTINSTALL`,
  `NSIS_HOOK_PREUNINSTALL`, `NSIS_HOOK_POSTUNINSTALL`.
- Tray-icon builds need `libayatana-appindicator3-dev` on the build host even
  when bundling for Windows (tauri-cli probes for it).
