# Warframe Market live-order proxy

Public read-only proxy for `obsidianoverseer.com/market.html`.

The item **catalog** stays on GitHub Pages (`/assets/wfm-items.json`).  
This service only serves **live orders**.

## Why not Deno?

Some Windows browsers hit `ERR_SSL_PROTOCOL_ERROR` on `*.deno.net` hosts.  
Prefer a **separate Railway service** (different URL from the Discord bot) for reliable HTTPS.

## Deploy on Railway (recommended)

1. Railway → **New** → **GitHub Repo** → `obsidian-clanbot`
2. Set **Root Directory** to `deploy/wfm-proxy`
3. Generate a public domain (Settings → Networking → Generate Domain)
4. Confirm start command is `python server.py` (from `railway.toml`)
5. Copy the URL (e.g. `https://obsidian-wfm-proxy.up.railway.app`) into `web/assets/config.js`:

```js
WFM_PROXY_URL: "https://YOUR-WFM-SERVICE.up.railway.app",
```

6. Commit/push that config change (or ask the agent to).

Do **not** point `WFM_PROXY_URL` at the Discord bot URL — that host was edge rate-limited.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/ping` | Health |
| `GET` | `/api/wfm/items/{slug}?platform=pc` | Item + live orders |

## Local test

```bash
cd deploy/wfm-proxy
pip install -r requirements.txt
python server.py
# curl http://127.0.0.1:8080/api/wfm/items/loki_prime_set
```

## Deno (optional)

`main.ts` remains for Deno Deploy if TLS works in your region. Prefer Railway if you see SSL errors.
