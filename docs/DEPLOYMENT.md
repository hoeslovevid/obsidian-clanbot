# Railway Deployment Guide

This guide will help you deploy the Obsidian Clan Bot to Railway.

## Build Errors

### mise Python attestation failure

If Railway diagnose mentions `MISE_PYTHON_GITHUB_ATTESTATIONS` or GitHub artifact attestations when installing Python, mise was updated and now verifies prebuilt Python binaries. Older patch releases may not have attestations.

This repo pins Python in `deploy/runtime.txt` / `deploy/mise.toml` and disables attestation checks for Python installs. Build settings live in `deploy/nixpacks.toml`; Railway reads `railway.toml` at the repo root. If you still see the error, add this **service variable** in Railway:

```
MISE_PYTHON_GITHUB_ATTESTATIONS=false
```

Then redeploy.

If Railpack cannot find `mise.toml` after it was moved into `deploy/`, add:

```
MISE_OVERRIDE_CONFIG_FILENAMES=deploy/mise.toml
```

Then redeploy.

### Transient Docker connection errors

If you see errors like:
```
ERROR: failed to build: listing workers for Build: failed to list workers: Unavailable: connection error
```

This is a **transient Docker connection error** during Railway's build phase. It's usually harmless if:
- The bot still goes online
- The deployment completes successfully
- The bot functions normally

This can happen due to:
- Temporary network issues during build
- Railway's Docker daemon having brief connection hiccups
- Build process timing

**Solution**: Usually no action needed. If it persists, try:
1. Redeploy the service
2. Check Railway's status page for known issues
3. Contact Railway support if it continues

## Prerequisites

1. A GitHub account
2. A Railway account (sign up at https://railway.app)
3. Your Discord bot token and configuration

## Step 1: Prepare Your Code

1. Make sure your code is in a Git repository (GitHub, GitLab, or Bitbucket)
2. Commit all changes including `deploy/Procfile`, `config/.gitignore`, and `railway.toml`

## Step 2: Create Railway Account & Project

1. Go to https://railway.app and sign up (you can use GitHub OAuth)
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Authorize Railway to access your GitHub account if prompted
5. Select your repository containing the bot code
6. Railway will automatically detect it's a Python project

## Step 3: Configure Environment Variables

1. In your Railway project, go to the "Variables" tab
2. Add the following environment variables (click "New Variable" for each):

### Required:
- `DISCORD_TOKEN` - Your Discord bot token

### Recommended:
- `GUILD_ID` - Your Discord server ID (faster command sync)
- `TEMP_VC_CATEGORY_ID` - Your Temp VCs category ID
- `MOD_ROLE_NAME` - Mod role name (default: "Obsidian Inheritor")

### Optional:
- `STEAM_API_KEY` - Steam Web API key for Warframe playtime roles (get at https://steamcommunity.com/dev/apikey)
- `TIMEZONE` - Timezone for event parsing (default: "America/New_York")
- `AUTO_SETUP` - Auto-create channels (default: "false"; run /setup_obsidian to configure)
- `VOICE_PANEL_CHANNEL_ID` - Voice panel channel ID
- `COMPLAINTS_CHANNEL_ID` - Complaints channel ID
- `EVENTS_CHANNEL_ID` - Events channel ID
- `DB_PATH` - Database path (default: `data/obsidian_clanbot.db`)

See `.env.example` for all available variables.

## Step 4: Configure Service Type

1. Go to the "Settings" tab of your service
2. Under "Service Type", make sure it's set to **"Worker"** (not Web Service)
   - Railway uses `railway.toml` → `startCommand = python run.py` (Worker)
   - Or set start command manually to `python run.py`

## Step 5: Deploy

1. Railway will automatically deploy when you push to your repository
2. Or click "Deploy" if you want to trigger a manual deployment
3. Watch the logs to see if deployment is successful

## Step 6: Monitor Your Bot

1. Go to the "Deployments" tab to see deployment history
2. Click on a deployment to view logs
3. Check that your bot is online in Discord

## Troubleshooting

### Bot doesn't start
- Check the logs in Railway for error messages
- Verify all required environment variables are set
- Make sure `DISCORD_TOKEN` is correct

### Bot crashes after starting
- Check logs for Python errors
- Verify privileged intents are enabled in Discord Developer Portal
- Ensure your bot has proper permissions in the Discord server

### Database issues

**IMPORTANT: Railway uses ephemeral storage by default!**

The database file gets **reset on every deployment** unless you use persistent storage.

**Solutions:**
1. **Use Railway Persistent Volume (Recommended):**
   - Add a Volume to your service (mount at `/data`)
   - Set `DB_PATH=/data/obsidian_clanbot.db` environment variable
   - See `RAILWAY_DATABASE.md` for detailed instructions

2. **Use Railway PostgreSQL Addon:**
   - Add PostgreSQL database from Railway dashboard
   - More reliable for production use
   - Requires code changes to use PostgreSQL instead of SQLite

3. **Use External Database:**
   - Supabase, Neon, PlanetScale, etc.
   - Persists independently of Railway deployments

**Without persistent storage, your database resets on every deployment!**

## Updating Your Bot

1. Make changes to your code locally
2. Commit and push to your GitHub repository
3. Railway will automatically redeploy
4. Or trigger a manual redeploy from the Railway dashboard

## Cost

Railway offers $5/month free credit, which is usually enough for small Discord bots. You'll only be charged if you exceed the free tier.

## Additional Resources

- Railway Docs: https://docs.railway.app
- Discord.py Docs: https://discordpy.readthedocs.io
