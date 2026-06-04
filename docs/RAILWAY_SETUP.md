# Railway Setup - Quick Fix for Missing DISCORD_TOKEN

## The Error
If you see: `RuntimeError: Missing DISCORD_TOKEN environment variable`

This means the `DISCORD_TOKEN` environment variable is not set in Railway.

## Solution: Add Environment Variable in Railway

1. **Go to Railway Dashboard**
   - Visit: https://railway.app
   - Open your project

2. **Navigate to Variables**
   - Click on your service (the worker)
   - Click on the **"Variables"** tab

3. **Add DISCORD_TOKEN**
   - Click **"New Variable"** or **"+ New"**
   - Name: `DISCORD_TOKEN`
   - Value: Your Discord bot token (paste it here)
   - Click **"Add"** or **"Save"**

4. **Get Your Discord Bot Token**
   - Go to: https://discord.com/developers/applications/
   - Select your bot application
   - Go to the **"Bot"** section
   - Click **"Reset Token"** or **"Copy"** to get your token
   - Paste it into Railway's Variables

5. **Deploy/Restart**
   - Railway will automatically restart the service with the new variable
   - Or click **"Redeploy"** if needed

## Other Required Variables (Recommended)

You may also want to add these:

- `GUILD_ID` - Your Discord server ID (faster command sync)
- `TEMP_VC_CATEGORY_ID` - Your Temp VCs category ID
- `MOD_ROLE_NAME` - Mod role name (default: "Obsidian Inheritor" if not set)

## Verification

After adding the token, check the Railway logs to confirm the bot starts successfully!
