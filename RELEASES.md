# Releasing desktop updates (publish once → every till updates)

The desktop app self-updates with **tufup** (signed updates — a compromised host
can't push arbitrary code). The update repo is hosted on the **POS Control Center**
(`pos_control`), so you publish a release in ONE place and every installed till pulls
it on its next launch. Tills read `ALPHA_POS_UPDATE_URL` (default:
`https://control.<ip>.nip.io/updates`, served by pos_control's Caddy `/updates`).

## How it flows
```
build box:  bump version -> build .exe -> tufup publish (signs) -> stage + verify
control host: promote target -> targets.json -> snapshot.json -> timestamp.json last
control center (pos_control):  <update-repo-path>  ->  served at /updates (Caddy)
each till:  on launch, updater.py checks /updates, downloads the newer signed build, restarts
```

## Cashier-frontend compatibility gate

Alpha POS Desktop 1.0.38 requires **Smart POS 0.0.11 or newer** on every
cashier station. Smart POS 0.0.11 is the first release approved for explicit
tender validation, persistent payment idempotency, and auditable CASH change.
The desktop backend rejects a non-zero order without valid tender evidence.

Before building or rolling out the desktop release:

1. Record the Smart POS version from each station's trusted deployment record
   or version display. Do not infer compatibility from successful login,
   product loading, or general API health; the backend cannot reliably identify
   a frontend version from an ordinary checkout request.
2. Stop the rollout if any station is below 0.0.11 or its version cannot be
   verified. Upgrade or verify the cashier frontend first.
3. Schedule the desktop change with no checkout in progress and, preferably,
   after the current shift has closed. Record the local sync-queue counts and
   the shift's cash/card totals before the upgrade.
4. Upgrade one canary station, then complete controlled cash, card, and (where
   used) split-tender checkouts. Confirm each order once in the local order
   ledger, confirm its tender breakdown, and confirm the sync queue drains
   without new rejected or quarantined records before wider rollout.

## Release steps (on the build box — the machine with `update_keys/`)
1. **Bump** `desktop/version.py` → `__version__` (must increase, e.g. `1.0.0` → `1.0.1`).
2. **Build:** `powershell -ExecutionPolicy Bypass -File build_installer.ps1`
   (produces `dist/AlphaPOS/` + the installer).
3. **Publish (sign):** `python tools/release.py --publish --bundle dist/AlphaPOS`
   → writes/updates `update_repo/metadata/` + `update_repo/targets/AlphaPOS-<ver>.tar.gz`.
4. **Stage and verify** the new target plus `targets.json`, `snapshot.json`, and
   `timestamp.json` under a same-filesystem staging directory on the control
   host. Before promotion, compute the staged archive's SHA-256 and byte length
   and compare both with its entry in signed `targets.json`. Do not continue if
   either value differs.
5. **Atomically promote** individual files in this exact order:
   `targets/AlphaPOS-<ver>.tar.gz` -> `metadata/targets.json` ->
   `metadata/snapshot.json` -> `metadata/timestamp.json`. The target must exist
   before metadata advertises it, and `timestamp.json` must always be last.
   See `OPERATIONS.md` for the generic staging, verification, and atomic-rename
   commands. Do not rsync or recursively copy the repository in arbitrary order.
6. Verify the public target and `metadata/timestamp.json`, then let a canary till
   check for the update before wider rollout.

## One-time / rules
- **`update_keys/` never leaves the build box** and must be backed up offline. Losing the
  **root** key = every till needs a reinstall to re-trust a new key set.
- **First install** of a till must use an installer built WITH the bundled `tuf_root/root.json`
  (the current build chain does this) so it can verify updates. Older installs need one
  manual reinstall to bootstrap trust.
- **Metadata expiry:** the local `.tufup-repo-config` currently requests 30 days
  for timestamp, snapshot, and targets metadata (root is configured separately),
  but each signed metadata file's `expires` field is authoritative. Check both
  before release rather than relying on a hard-coded lifetime:
  ```bash
  python -c "import json; print(json.load(open('.tufup-repo-config'))['expiration_days'])"
  python -c "import json; print(json.load(open('update_repo/metadata/timestamp.json'))['signed']['expires'])"
  ```
  Re-publish and safely promote fresh metadata before the signed expiry.
- `root.json` is unchanged for an ordinary release; do not stage or replace it.
- Never publish `update_keys/`, a private installer, or any support/restaurant
  configuration under `/updates`. Only the credential-free signed target and
  its public metadata belong there.
- Only the one-folder install auto-updates (not the portable one-file build).

## Make it one command (optional)
Wrap steps 1–6 in a `release.ps1` so a release is a single command. (A pos_control
admin button can't sign — keys stay on the build box — but it can host + show the
published version. The publish/stage/promote sequence is the build-box half.)
