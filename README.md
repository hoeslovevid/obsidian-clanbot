# Obsidian Clan Bot (Warframe Discord)

A refined Warframe clan bot with:
- **Join-to-create** temporary voice channels inside **Temp VCs**
- **Obsidian squad control panels** (rename/limit/lock/hide/invite/transfer/disband)
- **Obsidian Docket** (button → modal → case feed + staff thread)
- **Mod actions** with **DM status updates** to the user
- **Ops events** (natural time parsing, RSVP buttons, reminders, event thread)

## 1) Create a Discord application + bot
- Developer Portal → Applications → New Application
- Bot tab → Add Bot
- Enable **Server Members Intent**
- Copy token → paste into `.env` as `DISCORD_TOKEN`

## 2) Invite the bot
Generate an invite link with these permissions:
- Manage Channels
- Manage Messages (required for `/purge` command)
- Move Members
- View Channels / Connect / Speak
- Send Messages
- Embed Links
- Manage Threads (for staff/event threads)

Also give it `applications.commands` scope.

## 3) Configure `.env`
Copy `.env.example` → `.env`

At minimum:
- Set `DISCORD_TOKEN`
- Set `TEMP_VC_CATEGORY_ID` to your existing **Temp VCs** category ID (recommended)

Optional but recommended:
- Set `GUILD_ID` to your server ID (faster command sync during setup)

## 4) Install dependencies + run
```bash
pip install -r requirements.txt
python bot.py
```

## 5) What happens automatically
When the bot is installed or starts up, it will:
- Ensure the join-to-create voice channel **➕ Form Cell** exists in **Temp VCs**
- If `AUTO_SETUP=true`, it will create these text channels if missing:
  - `obsidian-console` (voice control panels)
  - `inheritor-docket`
  - `docket-ledger` (optional log)
  - `ops-board`

## 6) Place the Obsidian panels
Run this command in the channel where you want the panels to appear:
- `/setup_obsidian`

(Only members with the **Obsidian Inheritor** role can run it.)

## Commands
- `/setup_obsidian` — posts the Obsidian panels (mods only)
- `/event_create` — creates an ops event with RSVP buttons + reminder
- `/submit_complaint` — lets a user add more info to their case
- `/request_help` — lets a user check their case status
- `/purge` — clears messages from the current channel (mods only)
  - Usage: `/purge amount:<number 1-100> or "all"`

## Notes
- If a user has DMs closed, they may not receive complaint updates.
- Old buttons remain functional after bot restarts (persistent views are re-registered from the DB).
