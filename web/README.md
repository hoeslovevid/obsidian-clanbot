# Obsidian Overseer — Website

Static landing site for **Obsidian Overseer** ([obsidianoverseer.com](https://obsidianoverseer.com)).

This folder lives in the **obsidian-clanbot** monorepo next to the Discord bot. The bot links here via `BOT_WEBSITE` in `core/config.py`.

## Contents

- `index.html` — Hero, features, invite, developers, legal tabs
- `contact.html` — Contact form (Discord webhook or Netlify function)
- `legal.html` — Standalone legal page
- `assets/` — Images and static assets
- `CNAME` — Custom domain for GitHub Pages
- `netlify/` — Optional Netlify serverless contact handler

## Bot invite

Set `BOT_CLIENT_ID` at the bottom of `index.html` (already configured for production).

## Contact form & webhooks

**Do not commit Discord webhook URLs.** They grant post access to a channel.

| Host | Setup |
|------|--------|
| **GitHub Pages** (default) | Set `CONTACT_WEBHOOK_URL` in `contact.html` locally before deploy, or use a private channel and rotate if leaked. Form posts from the browser (URL visible in page source). |
| **Netlify** (optional) | Deploy with root `web/`, leave `CONTACT_WEBHOOK_URL` empty in HTML, set `CONTACT_WEBHOOK_URL` in Netlify env. Uses `netlify/functions/contact.mjs`. |

If you migrated from [obsidian-overseer-website](https://github.com/hoeslovevid/obsidian-overseer-website), **rotate any webhook that was in the old repo**.

## Hosting (GitHub Pages from monorepo)

1. **GitHub → Settings → Pages → Source:** GitHub Actions
2. Push to `main` — workflow `.github/workflows/deploy-website.yml` publishes the `web/` folder
3. Custom domain: `web/CNAME` → `obsidianoverseer.com` (DNS unchanged)

After switching from the standalone website repo, disable Pages on the old repo or point DNS only to this repo’s Pages to avoid conflicts.

## Future: mod dashboard

The bot exposes a JSON API when `DASHBOARD_API_ENABLED=true` (see `docs/DASHBOARD_API.md`). A dashboard UI can be added here as static pages + server-side proxy (Netlify functions or similar) — never expose `DASHBOARD_API_SECRET` in HTML/JS.

## Local preview

```bash
cd web
python -m http.server 8080
# open http://localhost:8080
```
