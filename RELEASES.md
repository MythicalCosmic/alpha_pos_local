# Releasing desktop updates (publish once → every till updates)

The desktop app self-updates with **tufup** (signed updates — a compromised host
can't push arbitrary code). The update repo is hosted on the **POS Control Center**
(`pos_control`), so you publish a release in ONE place and every installed till pulls
it on its next launch. Tills read `ALPHA_POS_UPDATE_URL` (default:
`https://control.<ip>.nip.io/updates`, served by pos_control's Caddy `/updates`).

## How it flows
```
build box:  bump version -> build .exe -> tufup publish (signs)  ->  upload update_repo/
control center (pos_control):  /srv/alpha_pos_updates  ->  served at /updates (Caddy)
each till:  on launch, updater.py checks /updates, downloads the newer signed build, restarts
```

## Release steps (on the build box — the machine with `update_keys/`)
1. **Bump** `desktop/version.py` → `__version__` (must increase, e.g. `1.0.0` → `1.0.1`).
2. **Build:** `powershell -ExecutionPolicy Bypass -File build_installer.ps1`
   (produces `dist/AlphaPOS/` + the installer).
3. **Publish (sign):** `python tools/release.py --publish --bundle dist/AlphaPOS`
   → writes/updates `update_repo/metadata/` + `update_repo/targets/AlphaPOS-<ver>.tar.gz`.
4. **Upload** the repo to the control-center server:
   ```
   rsync -a update_repo/  <control-server>:/srv/alpha_pos_updates/
   ```
   (or scp). That directory is what Caddy serves at `/updates`.
5. Done. Tills self-update on next launch; or from a till's panel → Updates → Check now.

## One-time / rules
- **`update_keys/` never leaves the build box** and must be backed up offline. Losing the
  **root** key = every till needs a reinstall to re-trust a new key set.
- **First install** of a till must use an installer built WITH the bundled `tuf_root/root.json`
  (the current build chain does this) so it can verify updates. Older installs need one
  manual reinstall to bootstrap trust.
- **Metadata expiry:** `.tufup-repo-config` `timestamp` expires fast (default 1 day) — raise
  it (e.g. 30) or re-publish on a cadence, or tills start rejecting a stale repo.
- Only the one-folder install auto-updates (not the portable one-file build).

## Make it one command (optional)
Wrap steps 1–4 in a `release.ps1` so a release is a single command. (A pos_control
admin button can't sign — keys stay on the build box — but it can host + show the
published version. The publish/upload is the build-box half.)
