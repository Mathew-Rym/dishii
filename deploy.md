# Dishii — Full Deployment Runbook
> dishii.co on Railway · Evolution API · Supabase · Custom Domain

---

## Quick-start (demo in under 2 hours)

1. Run `schema_final.sql` in Supabase → SQL Editor
2. `git push` the repo with the two Dockerfiles + `.streamlit/config.toml`
3. Create **dishii-web** service on Railway (Dockerfile) → add env vars → add custom domain `dishii.co`
4. Create **dishii-api** service on Railway (Dockerfile.api) → add env vars → add custom domain `api.dishii.co`
5. Create Evolution instance `dishii` → scan QR → set webhook URL to `https://api.dishii.co/webhook`
6. Point DNS at Railway (see Step 5)
7. Open `https://dishii.co`, log in with your phone number, upload a CSV

---

## Architecture

```
Manager browser
    │  login (OTP via WhatsApp)
    ▼
dishii.co  (Streamlit · Railway)  ──── reads/writes ──►  Supabase
    │  sends alerts/orders
    ▼
Evolution API  (Railway) ─── delivers ──►  WhatsApp (manager phones)
    │  receives reply
    │  POSTs webhook
    ▼
api.dishii.co  (FastAPI · Railway) ──── stores decision ──►  Supabase
```

Agent (cron on any server, or Railway cron): reclassifies inventory,
creates procurement requests, sends briefings every 30 min.

---

## Step 1 — Database setup (Supabase)

1. Go to **Supabase → SQL Editor → New query**
2. Paste the full contents of `schema_final.sql` and run it.
   - Drops and recreates all tables (fresh start)
   - Fixes `file_hash` unique per-store (multi-tenant bug fix)
   - Enables RLS with `allow_all` policy
   - Seeds admin, two demo stores, two managers
3. **Replace the placeholder phone numbers** in the seed section before running:
   - `254720521291` / `254720000000` → your WhatsApp number (platform admin)
   - `254711111111` → Alice's WhatsApp number (Mama Mboga owner)
   - `254722222222` → Bob's WhatsApp number (FreshLine owner)
4. Verify: the final `SELECT` statements at the bottom should show 12 tables
   and 2 stores, 2 managers.

> Note: phone numbers must be digits only with country code, no `+` or spaces.
> Example: Kenya +254 720 521291 → `254720521291`

---

## Step 2 — Prepare the repo

Files to add/update in the repo root:

```
dishii-main/
├── Dockerfile              ← web service (provided)
├── Dockerfile.api          ← webhook service (provided)
├── .dockerignore           ← (provided)
├── .env.example            ← (provided, DO NOT commit .env)
└── .streamlit/
    └── config.toml         ← (provided)
```

Copy the provided files into your repo, then:

```bash
git add Dockerfile Dockerfile.api .dockerignore .env.example .streamlit/config.toml
git add -A   # includes the patches from fix_dishii.sh + patch_multitenant.sh
git commit -m "feat: Railway deployment + multi-tenant isolation"
git push origin main
```

---

## Step 3 — Railway: create dishii-web (dashboard)

1. In your Railway project → **+ New Service → GitHub Repo**
2. Select your repo. Railway auto-detects the Dockerfile.
3. In the service → **Settings → Build**:
   - Builder: **Dockerfile**
   - Dockerfile Path: `Dockerfile`
4. In **Variables**, add all of these:
   ```
   SUPABASE_URL               = https://YOUR_PROJECT.supabase.co
   SUPABASE_KEY               = <anon key from Supabase → Settings → API>
   EVOLUTION_URL              = https://<evolution-railway-domain>
   EVOLUTION_KEY              = <AUTHENTICATION_API_KEY from Evolution service>
   EVOLUTION_INSTANCE         = dishii
   GCP_PROJECT_ID             =        (leave blank for demo)
   GCP_REGION                 = us-east5
   STREAMLIT_BROWSER_SERVER_ADDRESS = dishii.co
   ```
   > `STREAMLIT_BROWSER_SERVER_ADDRESS` is the key fix for WebSocket issues
   > on custom domains. Sets the URL Streamlit tells the browser to connect to.

5. **Deploy** the service.
6. In **Settings → Networking → Custom Domain**, add `dishii.co`.
   Railway shows a CNAME target like `xxxxxxxx.up.railway.app` — note it.

---

## Step 4 — Railway: create dishii-api (webhook)

1. Same Railway project → **+ New Service → GitHub Repo** → same repo.
2. **Settings → Build**:
   - Builder: **Dockerfile**
   - Dockerfile Path: `Dockerfile.api`
3. **Variables** (same values as web except `STREAMLIT_BROWSER_SERVER_ADDRESS`):
   ```
   SUPABASE_URL       = <same>
   SUPABASE_KEY       = <same>
   EVOLUTION_URL      = <same>
   EVOLUTION_KEY      = <same>
   EVOLUTION_INSTANCE = dishii
   ```
4. **Deploy** the service.
5. In **Settings → Networking → Custom Domain**, add `api.dishii.co`.
   Note the CNAME target (may differ from the web service).
6. Verify the service is live: `curl https://api.dishii.co/health`
   → should return `{"status":"ok"}`

---

## Step 5 — DNS at your registrar (Cloudflare recommended)

Cloudflare is free and handles apex-domain CNAME flattening automatically,
meaning `dishii.co` (no subdomain) can point to a Railway CNAME. Without it,
many registrars only allow `www.dishii.co` to use a CNAME.

### If you're NOT yet on Cloudflare:
1. Go to cloudflare.com → Add site → enter `dishii.co` → Free plan
2. Cloudflare shows your nameservers (e.g. `alice.ns.cloudflare.com`)
3. At your domain registrar, replace the nameservers with Cloudflare's two
4. Wait 5–30 min for propagation

### DNS records to add (Cloudflare dashboard → DNS):

| Type  | Name  | Target                              | Proxy |
|-------|-------|-------------------------------------|-------|
| CNAME | `@`   | `<dishii-web CNAME from Railway>`   | ✅ Proxied |
| CNAME | `api` | `<dishii-api CNAME from Railway>`   | ✅ Proxied |
| CNAME | `www` | `dishii.co`                         | ✅ Proxied |

> Enable **Proxied** (orange cloud) on all records. Cloudflare handles TLS.
> Railway also issues its own TLS certificate — both work, Cloudflare's is faster.

### Verify DNS:
```bash
dig dishii.co +short       # should return Cloudflare IPs
dig api.dishii.co +short   # should return Cloudflare IPs
curl -I https://dishii.co  # should return 200 (may take a few min after DNS propagates)
```

---

## Step 6 — Evolution API: create instance + connect WhatsApp

### 6a. Open the Evolution Manager UI

Navigate to your Evolution API Railway URL with `/manager` appended:
```
https://evolution-api-production-XXXX.up.railway.app/manager
```
Log in with your `EVOLUTION_KEY`.

### 6b. Create the instance

- Click **Create Instance**
- Name: `dishii` (must match `EVOLUTION_INSTANCE`)
- Type: **Baileys** (free, no Meta approval needed)
- Click **Create**

### 6c. Connect WhatsApp (scan QR)

- Click your `dishii` instance → **QR Code**
- Open WhatsApp on the phone that will send alerts → **Settings → Linked Devices → Link a Device**
- Scan the QR code
- Wait for status to show **open** or **connected** ✅

### 6d. Set the webhook

Use the Manager UI: Instance → **Webhook** → Enable → set URL:
```
https://api.dishii.co/webhook
```
Select event: **MESSAGES_UPSERT** only (you don't need the rest)
Save.

Or via curl:
```bash
curl -X POST "https://YOUR_EVOLUTION_URL/webhook/set/dishii" \
  -H "apikey: YOUR_EVOLUTION_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook": {
      "enabled": true,
      "url": "https://api.dishii.co/webhook",
      "webhookByEvents": false,
      "webhookBase64": false,
      "events": ["MESSAGES_UPSERT"]
    }
  }'
```

---

## Step 7 — Evolution API: stop storage filling up

In Railway → your Evolution API service → **Variables**, add these to stop
Evolution saving every WhatsApp message to Postgres (the biggest storage driver):

```
DATABASE_SAVE_DATA_INSTANCE=true
DATABASE_SAVE_DATA_NEW_MESSAGE=false
DATABASE_SAVE_MESSAGE_UPDATE=false
DATABASE_SAVE_DATA_CONTACTS=false
DATABASE_SAVE_DATA_CHATS=false
DATABASE_SAVE_DATA_LABELS=false
DATABASE_SAVE_DATA_HISTORIC=false
```

Keep `DATABASE_SAVE_DATA_INSTANCE=true` — required to remember the connected session.
The rest store message/chat/contact history you don't need (your app logs to Supabase).

Redeploy the Evolution API service after adding these vars.

---

## Step 8 — Running the cron agent

The `agent.py` script reclassifies inventory, creates procurement requests,
and sends WhatsApp briefings. Run it on a schedule.

### Option A: Railway cron service (same project, cheapest)

1. New Service → **Cron** in your Railway project
2. Command: `python agent.py`
3. Schedule: `*/30 * * * *` (every 30 minutes)
4. Add the same env vars as dishii-web

### Option B: Any Linux server / your laptop
```bash
# Add to crontab (crontab -e):
*/30 * * * * cd /path/to/dishii-main && /path/to/venv/bin/python agent.py >> /var/log/dishii-agent.log 2>&1
```

---

## Step 9 — Demo verification checklist

Run through this before the presentation:

- [ ] `https://dishii.co` loads the Dishii login page (not a Streamlit error)
- [ ] Log in with your admin phone → OTP arrives on WhatsApp → dashboard shows both stores
- [ ] Switch to "Mama Mboga Mart" → store selector shows only that store
- [ ] Log out → log in with Alice's phone → **only Mama Mboga Mart** visible (isolation ✅)
- [ ] Log in as Bob → **only FreshLine Foods** visible (isolation ✅)
- [ ] Upload a sample inventory CSV as Alice → traffic-light items appear on dashboard
- [ ] WhatsApp briefing/alert arrives on Alice's phone
- [ ] `curl https://api.dishii.co/health` → `{"status":"ok"}`
- [ ] Admin logs in → both stores visible in dropdown

### Demo isolation script (live, in front of audience):
1. "I'll log in as Alice from Mama Mboga Mart" — show only her store
2. "Now Bob from FreshLine — different business, different data" — show isolation
3. Upload Alice's inventory → dashboard populates, WhatsApp fires
4. Admin view — platform-wide visibility

---

## Environment variable quick reference

| Variable | dishii-web | dishii-api | agent.py |
|---|---|---|---|
| `SUPABASE_URL` | ✅ | ✅ | ✅ |
| `SUPABASE_KEY` | ✅ | ✅ | ✅ |
| `EVOLUTION_URL` | ✅ | ✅ | ✅ |
| `EVOLUTION_KEY` | ✅ | ✅ | ✅ |
| `EVOLUTION_INSTANCE` | ✅ | ✅ | ✅ |
| `GCP_PROJECT_ID` | optional | — | optional |
| `GCP_REGION` | optional | — | optional |
| `STREAMLIT_BROWSER_SERVER_ADDRESS` | `dishii.co` | — | — |

---

## After the demo — production hardening

These don't block the demo but should be done before real customers use it:

1. **Rotate the Supabase anon key** — the old `config.py` (now in `legacy_disabled/`)
   committed a key to git history. Even if the key is harmless, rotate it in
   Supabase → Settings → API → Regenerate anon key, then update Railway env vars.

2. **Add OTP rate limiting** — `auth.py` currently has no attempt cap on `verify_otp`.
   Add a counter column to `auth_otp` and reject after 5 attempts.

3. **Replace `allow_all` RLS with real policies** — requires minting a short-lived
   Supabase JWT per logged-in manager carrying their `store_id`:
   ```sql
   -- Example after JWT integration:
   CREATE POLICY "manager_own_store" ON inventory_items
     FOR ALL USING (
       store_id = (current_setting('request.jwt.claims', true)::jsonb->>'store_id')::uuid
     );
   ```

4. **Enable Cloudflare WAF rules** — free plan includes basic bot/DDoS protection.

5. **Set up Supabase database backups** — enabled by default on paid plans;
   schedule a weekly export on free plan via Supabase Dashboard → Backups.

6. **Private networking for Evolution API** — in Railway, enable Private Networking
   on the project and set `EVOLUTION_URL` on dishii-web and dishii-api to the
   internal hostname (shown in Evolution service → Settings → Network → Private):
   ```
   EVOLUTION_URL=http://evolution-api.railway.internal:8080
   ```
   This cuts egress costs and latency between your Railway services.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Blank white page on dishii.co | WebSocket blocked | Confirm `enableCORS=false` + `enableXsrfProtection=false` in CMD; confirm `STREAMLIT_BROWSER_SERVER_ADDRESS=dishii.co` in Railway vars |
| "Could not create upload record" after uploading same file twice | Old global `file_hash` unique constraint | Run `schema_final.sql` — fixes constraint to per-store |
| WhatsApp: Live shows Offline | Wrong `EVOLUTION_URL` or key | Check Evolution service Railway URL ends with no trailing slash; verify `AUTHENTICATION_API_KEY` matches `EVOLUTION_KEY` |
| OTP never arrives | WhatsApp not connected or wrong phone format | Open Evolution Manager → check instance state is `open`; phone must be digits only with country code |
| `api.dishii.co/health` returns 502 | dishii-api not deployed | Check Railway deployment logs for the api service |