# Warframe Market live-order proxy

Tiny Deno Deploy service that proxies warframe.market **v2** with CORS for `obsidianoverseer.com`.

Your custom domain does **not** need to be on Cloudflare — Deno gives you a free `*.deno.dev` URL.

## Why this exists

The marketing site cannot call `api.warframe.market` from the browser (no CORS).  
Calling the bot’s Railway URL for orders was failing with edge rate-limits (`Failed to fetch`).  
This proxy is a separate, lightweight host used only for live orders.

The item **catalog** still comes from GitHub Pages (`/assets/wfm-items.json`).

## One-time setup

1. Create a free account at [dash.deno.com](https://dash.deno.com).
2. Create a project named **`obsidian-wfm`** (or change `deno.json` / the workflow).
3. Install the CLI (optional, for local deploys):

   ```bash
   deno install -A jsr:@deno/deployctl -g
   ```

4. Deploy from this folder:

   ```bash
   cd deploy/wfm-proxy
   deployctl deploy --project=obsidian-wfm --entrypoint=main.ts
   ```

5. Copy the public URL (e.g. `https://obsidian-wfm-xxxx.deno.dev`) into `web/assets/config.js`:

   ```js
   WFM_PROXY_URL: "https://obsidian-wfm-xxxx.deno.dev",
   ```

6. Commit/push that config change so Pages picks it up.

### GitHub Actions (optional)

Repo → Settings → Secrets → Actions:

| Secret | Value |
|--------|--------|
| `DENO_DEPLOY_TOKEN` | Access token from Deno dashboard |
| `DENO_PROJECT` | `obsidian-wfm` (optional if you keep the default) |

Pushing changes under `deploy/wfm-proxy/**` runs [.github/workflows/deploy-wfm-proxy.yml](../../.github/workflows/deploy-wfm-proxy.yml).

After the first Action deploy, set `WFM_PROXY_URL` in `config.js` to the printed Deno URL (Actions cannot edit that for you safely).

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/ping` | Health |
| `GET` | `/api/wfm/items/{slug}?platform=pc` | Item + live orders |

## Local test

```bash
cd deploy/wfm-proxy
deno run -A main.ts
# then: curl http://127.0.0.1:8000/api/wfm/items/loki_prime_set
```
