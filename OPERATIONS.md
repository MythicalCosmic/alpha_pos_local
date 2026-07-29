# Alpha POS — Operations Cheat Sheet (plain language)

This is the "I'm tired, just tell me what to do" guide. Three projects, two servers.

## The map

| Thing | Where | What it does |
|---|---|---|
| **POS server** | `78.111.90.65` → `pos.78.111.90.65.nip.io` | The main POS API. Tills sync their sales/products UP to here. **The AI assistant runs here.** |
| **Control server** | `78.111.91.113` → `control.78.111.91.113.nip.io` | Licensing/plans/billing **and** hosts the desktop auto-updates at `/updates`. |
| **Desktop app** | Your PC | The Windows till app. Self-updates from the control server. |

**SSH into either server** using the release operator's own protected key:
```bash
export RELEASE_KEY="<path-to-private-ssh-key>"
export POS_HOST="<pos-server>"
export CONTROL_HOST="<control-server>"
export RELEASE_USER="<release-user>"

ssh -i "$RELEASE_KEY" "${RELEASE_USER}@${POS_HOST}"
ssh -i "$RELEASE_KEY" "${RELEASE_USER}@${CONTROL_HOST}"
```

---

## 1. Release a new desktop update (tills auto-update)

Run on **this PC** (the build box — it has the signing keys in `update_keys/`):

**Required cashier preflight:** Alpha POS Desktop 1.0.39 supports Smart POS
**0.0.11 or newer**. Smart POS 0.0.11 must send explicit tender lines, retain a
stable payment idempotency key across uncertain retries, and preserve CASH
given for customer change. The hardened backend rejects ambiguous payment
evidence instead of silently recording it as cash.

There is no reliable server-side version detection for an ordinary checkout.
Before upgrading, manually record the Smart POS version from each station's
trusted version display or deployment record. Stop if any version is below
0.0.11 or cannot be verified. With checkouts stopped and preferably after shift
close, record the local queue counts and cash/card totals. Upgrade one canary
station first, perform controlled cash, card, and any supported split-tender
checkouts, and verify one local order/payment record per sale plus a clean sync
queue before updating the remaining stations. General API connectivity alone
does not pass this gate.

For a stuck treasury-eligible shift, close it on the restaurant desktop—not
from the cloud mirror. A manager may use `POST /shifts/{shift_id}/end` on the
local API only after physically counting every tender. Submit `CASH`, `UZCARD`,
`HUMO`, `CARD`, and `PAYME`, including explicit zeroes. The server returns
`terminal_close_required` when a cloud caller tries to create settlement
evidence for a restaurant-origin shift.

The following release block uses **Git Bash syntax**, including `export`,
forward slashes, heredocs, and line continuations. Do not paste it directly
into PowerShell.

```bash
cd /c/Users/mythi/OneDrive/Desktop/AlphaPOS-Split/alpha_pos_local

# 1. Edit desktop/version.py -> bump __version__ (e.g. "1.0.2" -> "1.0.3"). Must go UP.

# 2. Build the app + precompiled UI + icon + versioned deliverables:
powershell -ExecutionPolicy Bypass -File build_installer.ps1

# 3. Sign + package it:
../.venv/Scripts/python.exe tools/release.py --publish --bundle dist/AlphaPOS

# 4. Set release-specific, non-secret values:
export VERSION="<NEWVERSION>"
export TARGET="AlphaPOS-${VERSION}.tar.gz"
export RELEASE_KEY="<path-to-private-ssh-key>"
export CONTROL_HOST="<control-server>"
export RELEASE_USER="<release-user>"
export UPDATE_BASE_URL="https://<control-server>/updates"
export LIVE_REPO="<control-host-update-repo-path>"
export STAGE_REPO="${LIVE_REPO}/.staging-${VERSION}-$(date +%s)"

# 5. Verify the archive against the hash and length in signed targets.json:
../.venv/Scripts/python.exe - "$TARGET" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

name = sys.argv[1]
archive = Path("update_repo/targets") / name
metadata = json.loads(
    Path("update_repo/metadata/targets.json").read_text(encoding="utf-8")
)
expected = metadata["signed"]["targets"].get(name)
if expected is None:
    raise SystemExit(f"{name} is not advertised by signed targets.json")
actual_length = archive.stat().st_size
hasher = hashlib.sha256()
with archive.open("rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        hasher.update(chunk)
actual_hash = hasher.hexdigest()
if actual_length != expected["length"]:
    raise SystemExit("target length does not match signed targets.json")
if actual_hash != expected["hashes"]["sha256"]:
    raise SystemExit("target SHA-256 does not match signed targets.json")
print(f"verified {name}: {actual_length} bytes, sha256={actual_hash}")
PY

# 6. Stage only the new target and ordinary-release metadata:
ssh -i "$RELEASE_KEY" "${RELEASE_USER}@${CONTROL_HOST}" \
  "install -d -m 0755 '$STAGE_REPO/targets' '$STAGE_REPO/metadata'"
scp -i "$RELEASE_KEY" "update_repo/targets/$TARGET" \
  "${RELEASE_USER}@${CONTROL_HOST}:$STAGE_REPO/targets/$TARGET"
for role in targets snapshot timestamp; do
  scp -i "$RELEASE_KEY" "update_repo/metadata/${role}.json" \
    "${RELEASE_USER}@${CONTROL_HOST}:$STAGE_REPO/metadata/${role}.json"
done

# 7. Recheck the staged target on the server before exposing any metadata:
ssh -i "$RELEASE_KEY" "${RELEASE_USER}@${CONTROL_HOST}" \
  python3 - "$STAGE_REPO" "$TARGET" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

stage = Path(sys.argv[1])
name = sys.argv[2]
archive = stage / "targets" / name
metadata = json.loads(
    (stage / "metadata" / "targets.json").read_text(encoding="utf-8")
)
expected = metadata["signed"]["targets"].get(name)
if expected is None:
    raise SystemExit(f"{name} is not advertised by staged targets.json")
actual_length = archive.stat().st_size
hasher = hashlib.sha256()
with archive.open("rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        hasher.update(chunk)
actual_hash = hasher.hexdigest()
if actual_length != expected["length"]:
    raise SystemExit("staged target length mismatch")
if actual_hash != expected["hashes"]["sha256"]:
    raise SystemExit("staged target SHA-256 mismatch")
print(f"verified staged {name}")
PY

# 8. Promote by same-filesystem atomic renames in dependency-safe order.
#    timestamp.json MUST be last. Stop immediately if any command fails.
ssh -i "$RELEASE_KEY" "${RELEASE_USER}@${CONTROL_HOST}" \
  sh -s -- "$STAGE_REPO" "$LIVE_REPO" "$TARGET" <<'SH'
set -eu
stage=$1
live=$2
target=$3
mv -f -- "$stage/targets/$target" "$live/targets/$target"
mv -f -- "$stage/metadata/targets.json" "$live/metadata/targets.json"
mv -f -- "$stage/metadata/snapshot.json" "$live/metadata/snapshot.json"
mv -f -- "$stage/metadata/timestamp.json" "$live/metadata/timestamp.json"
rmdir "$stage/targets" "$stage/metadata" "$stage"
SH
```

Every till self-updates on its next launch. Verify it's live:
```bash
curl --fail --head "$UPDATE_BASE_URL/targets/$TARGET"
curl --fail "$UPDATE_BASE_URL/metadata/timestamp.json" >/dev/null
```

Availability probes are not a release proof. Before allowing wider rollout,
download the public target and all four public metadata roles into a clean
directory, verify the TUF signature chain from the installer-bundled trusted
`root.json`, and confirm the downloaded target's signed length and SHA-256.
Then exercise one installed canary through the normal updater and inspect its
shutdown, helper, startup, backend-health, and rollback state.

**Release rules:**
- **Back up `update_keys/`** (offline). Lose the root key = every till must be reinstalled.
- Never upload `update_keys/`, a private installer, or any support/restaurant
  configuration to the public update repository.
- `root.json` is unchanged during an ordinary release. Do not stage or replace it.
- The local repository currently requests 30 days for timestamp, snapshot, and
  targets metadata (root is configured separately), but each signed `expires`
  value is authoritative. Check the configuration and hosted timestamp instead
  of assuming:
  ```bash
  ../.venv/Scripts/python.exe -c "import json; print(json.load(open('.tufup-repo-config'))['expiration_days'])"
  curl --fail --silent "$UPDATE_BASE_URL/metadata/timestamp.json" | \
    ../.venv/Scripts/python.exe -c "import json,sys; print(json.load(sys.stdin)['signed']['expires'])"
  ```
  Re-publish and safely promote fresh metadata before it expires.

---

## 2. The AI assistant (server-side, Gemini)

The AI answers business questions ("what are the sales today", "top products", "low stock").
It runs **only on the POS server** — the desktop has no AI (no keys on tills).

**Change the Gemini key / model:**
```bash
ssh -i "$RELEASE_KEY" "${RELEASE_USER}@${POS_HOST}"
cd /root/alpha_pos_server
# edit .env: GEMINI_API_KEY=...   (AI_PROVIDER=gemini, GEMINI_MODEL=gemini-2.5-flash)
docker compose -f docker-compose.yaml -f docker-compose.edge.yml up -d web
```
(The key survives redeploys — `deploy.sh` preserves it.)

**Ask it a question manually (to test):**
```bash
ssh -i "$RELEASE_KEY" "${RELEASE_USER}@${POS_HOST}" \
  "docker exec -i alpha_pos_server-web-1 python manage.py shell" <<'PY'
from stock.services.ai_assistant_service import AIStockAssistant
print(AIStockAssistant.process_query("What are the sales today?")["response"])
PY
```
The real app calls it at `POST …/ai/query/` (admin login required).

---

## 3. Subscription plans (the licensing/plans page)

If the plans page is empty, seed the standard tiers on the control server:
```bash
ssh -i "$RELEASE_KEY" "${RELEASE_USER}@${CONTROL_HOST}" \
  "docker exec -i pos_control-web-1 python manage.py seed_plans"
```
Check: `curl "https://<control-server>/api/v1/plans"`. Edit prices at
`https://<control-server>/admin/billing/subscriptionplan/`.
Use an individually provisioned administrator account; production credentials
must never be stored in this repository.

---

## 4. Redeploy a server after pushing code

```bash
ssh -i "$RELEASE_KEY" "${RELEASE_USER}@${POS_HOST}" \
  "cd <path-to-alpha_pos_server> && ./deploy.sh <pos-public-ip>"
ssh -i "$RELEASE_KEY" "${RELEASE_USER}@${CONTROL_HOST}" \
  "cd <path-to-pos_control> && ./deploy.sh <control-public-ip>"
```
Deploy pulls latest git, rebuilds containers, runs migrations, (re)creates admin users.

---

## 5. Courier QR authority (local vs cloud)

Courier login QR codes are intentionally bound to the Django installation that
provisioned them. The `qr.server` value is built from the provisioning request's
own scheme/host (`request.build_absolute_uri('/')`); the mobile app must use that
same server for login, refresh, orders, location and payment calls.

- A courier created through the desktop endpoint `/api/couriers/create` receives
  the till's LAN URL and talks directly to that till.
- A courier created through the cloud admin endpoint receives the public cloud
  URL and talks to the cloud deployment.
- `Courier` and `DeliveryAssignment` are local authority tables, not SyncMixin
  models. A courier provisioned in one deployment does not automatically exist
  in the other. Do not replace the QR's `server` with a hard-coded cloud or LAN
  URL: its one-time claim and later access/refresh records exist only on the
  issuing database.

Therefore one restaurant must choose one dispatch authority for a courier fleet.
The current local cashier picker cannot see couriers provisioned only in cloud,
and a cloud rider cannot consume a local-only assignment. Supporting riders
outside the store LAN while dispatch stays on the till requires an explicit
sync/proxy design; that cross-authority workflow is not provided by the current
model.

---

## 6. Telegram receipt auto-print contract

Do not implement auto-print by scanning `GET /orders`, remembering IDs in
browser storage, or assuming the first page contains every new order. The till
keeps a durable, local print ledger. An authenticated ADMIN/MANAGER/CASHIER POS
client uses this loop:

1. `POST /orders/print-jobs/claim`
2. If `data.job` is `null`, wait and poll again (an order WebSocket event may be
   used only as a wake-up hint).
3. Print `data.job.order`, which is the complete order-detail projection.
4. Only after the printer/spooler reports success, call
   `POST /orders/print-jobs/{claim_token}/ack`.
5. If the printer definitely did not accept the job, call
   `POST /orders/print-jobs/{claim_token}/fail` with `{"error": "..."}`.

Repeating claim from the same authenticated session returns its existing lease;
repeating ACK is idempotent. A retry receives a new fencing token, so an old,
late ACK cannot complete the replacement attempt. Existing orders are marked as
handled during migration and the activation timestamp also prevents a later
cloud POS-to-TELEGRAM origin backfill from replaying historical tickets.

The desktop repository contains only the backend control panel; it has no
cashier order UI, printer selection, receipt renderer, or native/ESC-POS spooler.
The actual cashier frontend must provide step 3. No distributed protocol can
guarantee exactly one physical sheet if a process dies after paper is printed
but before ACK; this claim/ACK ledger guarantees one active consumer, retries
unacknowledged work, and never redelivers an acknowledged receipt.
