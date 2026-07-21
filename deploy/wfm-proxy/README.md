# Warframe Market live-order proxy

Public read-only proxy for `obsidianoverseer.com/market.html`.

The item **catalog** stays on GitHub Pages (`/assets/wfm-items.json`).  
This service only serves **live orders**.

## Why not Deno?

Some Windows browsers hit `ERR_SSL_PROTOCOL_ERROR` on `*.deno.net` hosts.  
Prefer a **separate Railway service** (different URL from the Discord bot) for reliable HTTPS.

## Deploy on Railway (recommended)

1. Railway → **New** → **GitHub Repo** → `obsidian-clanbot`  
   (or open the service whose domain is `obsidianclanbot-production.up.railway.app`)
2. **Settings → Root Directory** = `deploy/wfm-proxy` (required)
3. **Settings → Build** should use the Dockerfile in that folder
4. **Settings → Deploy** start command: `python server.py`
5. **Networking → Generate Domain** (you already have one)
6. Check **Deployments → Logs** for `[wfm-proxy] Listening on 0.0.0.0:…`
7. Test: `https://YOUR-DOMAIN.up.railway.app/api/ping` → `{"ok":true,"service":"wfm-proxy",...}`

If you see **502 Application failed to respond**, Root Directory is almost always wrong
(Railway is starting the Discord bot instead of this proxy).

Then set in `web/assets/config.js`:

```js
WFM_PROXY_URL: "https://YOUR-DOMAIN.up.railway.app",
```

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
