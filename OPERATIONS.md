# Alpha POS — Operations Cheat Sheet (plain language)

This is the "I'm tired, just tell me what to do" guide. Three projects, two servers.

## The map

| Thing | Where | What it does |
|---|---|---|
| **POS server** | `78.111.90.65` → `pos.78.111.90.65.nip.io` | The main POS API. Tills sync their sales/products UP to here. **The AI assistant runs here.** |
| **Control server** | `78.111.91.113` → `control.78.111.91.113.nip.io` | Licensing/plans/billing **and** hosts the desktop auto-updates at `/updates`. |
| **Desktop app** | Your PC | The Windows till app. Self-updates from the control server. |

**SSH into either server** (one key works for both):
```bash
cp "/c/Users/mythi/OneDrive/Desktop/Server/alpha_pos.pem" /tmp/alpha_pos_key && chmod 600 /tmp/alpha_pos_key
ssh -i /tmp/alpha_pos_key root@78.111.90.65      # POS server
ssh -i /tmp/alpha_pos_key root@78.111.91.113     # control server
```

---

## 1. Release a new desktop update (tills auto-update)

Run on **this PC** (the build box — it has the signing keys in `update_keys/`):

```bash
cd /c/Users/mythi/OneDrive/Desktop/AlphaPOS-Split/alpha_pos_local

# 1. Edit desktop/version.py -> bump __version__ (e.g. "1.0.2" -> "1.0.3"). Must go UP.

# 2. Build the app + precompiled UI + icon + versioned deliverables:
powershell -ExecutionPolicy Bypass -File build_installer.ps1

# 3. Sign + package it:
../.venv/Scripts/python.exe tools/release.py --publish --bundle dist/AlphaPOS

# 4. Upload to the CONTROL server (that's what tills download from):
scp -i /tmp/alpha_pos_key -r update_repo/metadata root@78.111.91.113:/srv/alpha_pos_updates/
scp -i /tmp/alpha_pos_key update_repo/targets/AlphaPOS-<NEWVERSION>.tar.gz root@78.111.91.113:/srv/alpha_pos_updates/targets/
```

Every till self-updates on its next launch. Verify it's live:
```bash
curl https://control.78.111.91.113.nip.io/updates/metadata/timestamp.json   # expect 200
```

**Two warnings:**
- **Back up `update_keys/`** (offline). Lose the root key = every till must be reinstalled.
- The update metadata **expires after 1 day**. If you don't release for a while, tills
  reject it as stale. Fix: raise `expiration_days.timestamp` in `.tufup-repo-config` and
  re-run steps 3–4, or just re-publish when you next release.

---

## 2. The AI assistant (server-side, Gemini)

The AI answers business questions ("what are the sales today", "top products", "low stock").
It runs **only on the POS server** — the desktop has no AI (no keys on tills).

**Change the Gemini key / model:**
```bash
ssh -i /tmp/alpha_pos_key root@78.111.90.65
cd /root/alpha_pos_server
# edit .env: GEMINI_API_KEY=...   (AI_PROVIDER=gemini, GEMINI_MODEL=gemini-2.5-flash)
docker compose -f docker-compose.yaml -f docker-compose.edge.yml up -d web
```
(The key survives redeploys — `deploy.sh` preserves it.)

**Ask it a question manually (to test):**
```bash
ssh -i /tmp/alpha_pos_key root@78.111.90.65 \
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
ssh -i /tmp/alpha_pos_key root@78.111.91.113 \
  "docker exec -i pos_control-web-1 python manage.py seed_plans"
```
Check: `curl https://control.78.111.91.113.nip.io/api/v1/plans`. Edit prices at
`https://control.78.111.91.113.nip.io/admin/billing/subscriptionplan/`.
Use an individually provisioned administrator account; production credentials
must never be stored in this repository.

---

## 4. Redeploy a server after pushing code

```bash
ssh -i /tmp/alpha_pos_key root@78.111.90.65   "cd /root/alpha_pos_server && ./deploy.sh 78.111.90.65"
ssh -i /tmp/alpha_pos_key root@78.111.91.113  "cd /root/pos_control && ./deploy.sh 78.111.91.113"
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
