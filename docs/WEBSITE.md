# Website (monorepo)

The public site lives in [`web/`](../web/) — migrated from [obsidian-overseer-website](https://github.com/hoeslovevid/obsidian-overseer-website).

## Pages

| Path | Purpose |
|------|---------|
| `/` | Home + features |
| `/dashboard.html` | Mod dashboard (Discord OAuth → bot API) |
| `/contact.html` | Contact form → `POST /api/contact` on the bot |
| `/legal.html` | Privacy & terms |
| `/404.html` | GitHub Pages fallback |

Shared nav is rendered by [`web/assets/site.js`](../web/assets/site.js) (Home, Features, Dashboard, Contact, Legal). All internal links use root paths (`/contact.html`, not `contact.html`) so GitHub Pages routing works on the custom domain.

## Deploy

| What | Where |
|------|--------|
| Site files | `web/` |
| Custom domain | `web/CNAME` → `obsidianoverseer.com` |
| CI | `.github/workflows/deploy-website.yml` |
| Bot link | `BOT_WEBSITE` in `core/config.py` |

### Switch from standalone repo

1. In **this** repo: Settings → Pages → **GitHub Actions** as source (not “Deploy from branch / root”).
2. Push `main` — workflow uploads `web/` as the Pages artifact.
3. **Do not** add `CNAME` at the repo root — only `web/CNAME` (root `CNAME` makes legacy Pages serve `README.md` instead of the site).
4. Confirm `obsidianoverseer.com` still resolves (same CNAME file in `web/`).
5. On the old [obsidian-overseer-website](https://github.com/hoeslovevid/obsidian-overseer-website) repo: disable Pages or archive the repo to avoid double deploys.
6. **Rotate** the Discord contact webhook if it was committed in the old repo.

## Connect site ↔ bot

Edit [`web/assets/config.js`](../web/assets/config.js):

```js
window.OBSIDIAN_SITE = {
  BOT_API_URL: "https://YOUR-RAILWAY-APP.up.railway.app",
  DISCORD_CLIENT_ID: "your-app-client-id",
};
```

On Railway (or wherever the bot runs):

| Variable | Purpose |
|----------|---------|
| `DASHBOARD_API_ENABLED=true` | Starts the HTTP API (contact + dashboard) |
| `CONTACT_WEBHOOK_URL` | Discord webhook for contact form submissions |
| `DASHBOARD_CORS_ORIGINS=https://obsidianoverseer.com` | Browser CORS for site → bot |
| `DISCORD_CLIENT_ID` | Same as in config.js (OAuth) |
| `DISCORD_CLIENT_SECRET` | Discord app client secret — required for reliable dashboard login |
| `DASHBOARD_API_SECRET` | Optional; for backend/service auth only |

In the [Discord Developer Portal](https://discord.com/developers/applications): add OAuth redirect URI:

`https://obsidianoverseer.com/dashboard.html`

Also copy **OAuth2 → Client Secret** into Railway as `DISCORD_CLIENT_SECRET`, then redeploy.

See [DASHBOARD_API.md](DASHBOARD_API.md) for API endpoints and auth flow.

Do not put webhooks or API secrets in `web/*.html`.

### Live server / user counts (home page)

The home page “Servers / Users” counters read `web/assets/bot-stats.json`.

GitHub Actions refreshes that file **hourly** (workflow **Update bot stats**) by calling the Discord API — not Railway — so it keeps working even if the public bot API is rate-limited.

**Required once:** add a repository secret named `DISCORD_TOKEN` (same value as Railway’s `DISCORD_TOKEN`):

Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Then run **Actions → Update bot stats → Run workflow**, or wait for the next hourly schedule.
