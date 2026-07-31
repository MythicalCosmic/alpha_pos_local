# Private Alpha POS installer

Public Alpha POS builds contain no restaurant or support credentials. A private
installer is an explicit, separate release artifact for a specific authorized
deployment. Anyone holding that installer can recover the embedded support
credentials, so store and transfer it like a private key.

## Build

The version remains controlled by `desktop/version.py`. After the release owner
sets the intended version, run:

```powershell
$Version = '1.0.40'
powershell -ExecutionPolicy Bypass -File .\build_installer.ps1 `
  -PrivateSupportConfig ".\DELIVERABLES\AlphaPOS-$Version-Support-Config.json"
```

The source JSON must be outside the repository or ignored by Git. The build
validates it without printing values, creates a DACL-protected temporary payload
under ignored `build\private-release`, passes that path to Inno Setup, and
removes the staged plaintext in a `finally` block.

The private output is named separately:

```text
DELIVERABLES\AlphaPOS-<version>-Private-Setup.exe
DELIVERABLES\AlphaPOS-Private-Setup.exe
```

Running `build_installer.ps1` without `-PrivateSupportConfig` follows the public
path. No payload macro is passed to Inno Setup and no credential file is added.
Portable executables are always public and credential-free.

## Install and merge behavior

Run the private installer as the same Windows user that owns the restaurant
installation, then launch Alpha POS. Before Django starts, a runtime hook:

1. validates the embedded payload and its SSH host pin/private-key structure;
2. accepts only `SUPPORT_TUNNEL_*`, owner order-audit recipients,
   `LOCAL_TELEGRAM_*` settings, and the exact `ALPHA_POS_UPDATE_URL` already
   baked into this release;
3. atomically merges those fields into `%LOCALAPPDATA%\AlphaPOS\.env`;
4. restores an older blank or stale update URL to that canonical signed-update
   endpoint while preserving branch, cloud-sync, database, licensing, and
   fiscal settings;
5. keeps an existing nonblank secret when the payload value is blank or masked;
6. writes only a non-secret SHA-256 applied marker; and
7. removes the installed plaintext payload.

The digest marker makes the operation idempotent if deletion is interrupted.
Invalid payloads are rejected without changing `.env` and cannot stop checkout
from booting.

The protected source JSON does not need to contain `ALPHA_POS_UPDATE_URL`.
Staging inserts the baked canonical value automatically so an upgraded private
installer receives a new digest and repairs the updater setting on first
launch. If the source explicitly supplies any other URL, including a
trailing-slash or whitespace variant, validation fails rather than redirecting
the till.

After launch, confirm the panel reports the expected private-support settings.
Do not run the home connector until both **DB Ready** and **Backend Ready** are
shown.
