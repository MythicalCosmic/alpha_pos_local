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

# 2. Build the app (via Bash, NOT the PowerShell Tee trick):
SECRET_KEY=x DEBUG=True ../.venv/Scripts/pyinstaller.exe --noconfirm --clean AlphaPOS.spec

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
`https://control.78.111.91.113.nip.io/admin/billing/subscriptionplan/` (admin / root1234).

---

## 4. Redeploy a server after pushing code

```bash
ssh -i /tmp/alpha_pos_key root@78.111.90.65   "cd /root/alpha_pos_server && ./deploy.sh 78.111.90.65"
ssh -i /tmp/alpha_pos_key root@78.111.91.113  "cd /root/pos_control && ./deploy.sh 78.111.91.113"
```
Deploy pulls latest git, rebuilds containers, runs migrations, (re)creates admin users.
