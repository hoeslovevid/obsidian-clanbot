# Website (monorepo)

The public site lives in [`web/`](../web/) — migrated from [obsidian-overseer-website](https://github.com/hoeslovevid/obsidian-overseer-website).

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
5. **Rotate** the Discord contact webhook if it was committed in the old repo (see `web/README.md`).

## Dashboard integration

See [DASHBOARD_API.md](DASHBOARD_API.md). The site is static HTML today; a mod dashboard needs either:

- Netlify/serverless routes that proxy to the bot API with `DASHBOARD_API_SECRET`, or
- New pages under `web/` that call your own backend.

Do not put API secrets in `web/*.html`.
