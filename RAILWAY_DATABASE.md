# Railway Database Persistence Guide

## The Problem

Railway uses **ephemeral storage** by default. This means:
- Files are stored in the container's temporary filesystem
- The database file gets **reset on every deployment/redeploy**
- Settings, data, and configurations are lost when the service restarts

## Solutions

### Option 1: Use Railway Persistent Volume (Recommended for Railway)

Railway offers persistent volumes that survive deployments:

1. **Add a Volume to your Railway service:**
   - Go to your Railway project
   - Click on your service
   - Go to the **"Volumes"** tab
   - Click **"New Volume"**
   - Name it: `bot-data` (or any name you prefer)
   - Mount path: `/data`
   - Click **"Add"**

2. **Set the DB_PATH environment variable:**
   - Go to **"Variables"** tab
   - Add new variable:
     - Name: `DB_PATH`
     - Value: `/data/obsidian_clanbot.db`
   - Click **"Add"**

3. **Redeploy your service:**
   - Railway will automatically redeploy
   - The database will now persist in the mounted volume

### Option 2: Use Railway PostgreSQL Addon (Best for Production)

For production use, Railway's PostgreSQL addon is more reliable:

1. **Add PostgreSQL to your project:**
   - In Railway dashboard, click **"+ New"**
   - Select **"Database"** → **"Add PostgreSQL"**
   - Railway will create a PostgreSQL database

2. **Get the connection string:**
   - Click on the PostgreSQL service
   - Go to **"Variables"** tab
   - Copy the `DATABASE_URL` value

3. **Update your bot to use PostgreSQL:**
   - You'll need to modify the code to use `asyncpg` or `psycopg2` instead of `aiosqlite`
   - Or use a library like `databases` that supports both SQLite and PostgreSQL

### Option 3: Use External Database Service

Use an external database service that persists independently:

- **Supabase** (free tier available)
- **Neon** (serverless PostgreSQL, free tier)
- **PlanetScale** (MySQL, free tier)
- **Railway PostgreSQL** (as mentioned above)

## Verifying Database Persistence

After setting up persistent storage, check the Railway logs for:

```
[startup] Database path: /data/obsidian_clanbot.db
[startup] Database directory: /data
[startup] Database file found: /data/obsidian_clanbot.db (XXXX bytes)
```

If you see the database file size increasing over time, persistence is working!

## Current Database Path

The bot uses the `DB_PATH` environment variable, defaulting to `obsidian_clanbot.db` in the current directory.

**Without a persistent volume:**
- Database is stored in the container's ephemeral filesystem
- Data is lost on every deployment

**With a persistent volume:**
- Database is stored in the mounted volume (e.g., `/data/obsidian_clanbot.db`)
- Data persists across deployments

## Quick Setup (Persistent Volume)

**Note:** Volumes may not be available on Railway's free tier. If you don't see a Volumes option, use Option 2 (PostgreSQL) instead.

1. Railway Dashboard → Your Service → Look for **"Volumes"** (in Settings tab or as a separate tab)
2. If available, click **"New Volume"** or **"+ Add Volume"**
3. **Mount path:** Enter `/data` (this is the directory path inside the container)
4. **Name:** Enter `bot-data` (or any name - just a label)
5. Variables tab → Add `DB_PATH=/data/obsidian_clanbot.db`
6. Redeploy

**What is Mount Path?**
- The mount path is the directory path **inside your container** where the volume will be accessible
- `/data` means the volume will be mounted at the `/data` directory
- Your bot will save files to `/data/obsidian_clanbot.db` which will persist across deployments

**If Volumes aren't available:** Use Railway's PostgreSQL addon (Option 2) - it's free and more reliable!

Your database will now persist! 🎉
