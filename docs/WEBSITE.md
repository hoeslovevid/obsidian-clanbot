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

1. In **this** repo: Settings → Pages → **GitHub Actions** as source.
2. Push `main` — workflow uploads `web/` as the Pages artifact.
3. Confirm `obsidianoverseer.com` still resolves (same CNAME file).
4. On the old [obsidian-overseer-website](https://github.com/hoeslovevid/obsidian-overseer-website) repo: disable Pages or archive the repo to avoid double deploys.
5. **Rotate** the Discord contact webhook if it was committed in the old repo.

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
| `DASHBOARD_API_SECRET` | Optional; required for authenticated dashboard API calls from a backend proxy |

In the [Discord Developer Portal](https://discord.com/developers/applications): add OAuth redirect URI:

`https://obsidianoverseer.com/dashboard.html`

See [DASHBOARD_API.md](DASHBOARD_API.md) for API endpoints and auth flow.

Do not put webhooks or API secrets in `web/*.html`.
