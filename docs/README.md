# Obsidian Clan Bot (Warframe Discord)

A Warframe clan Discord bot with voice channels, applications, complaints, events, economy, XP, pets, Warframe game integration, and more.

---

## Quick Start

1. [Create a Discord application + bot](#1-create-a-discord-application--bot)
2. [Invite the bot](#2-invite-the-bot)
3. [Configure environment variables](#3-configure-environment-variables)
4. [Install and run](#4-install-and-run)
5. [First-time setup](#5-first-time-setup)

---

## 1) Create a Discord application + bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications) → **Applications** → **New Application**
2. Open the **Bot** tab → **Add Bot**
3. Enable **Server Members Intent** (required for economy, XP, member tracking)
4. Copy the bot token → save it for step 3

---

## 2) Invite the bot

Generate an invite link with these **permissions**:

| Permission          | Used for                                           |
|---------------------|----------------------------------------------------|
| Manage Channels     | Temp voice channels, join-to-create                |
| Manage Roles        | Level roles, achievement roles, reaction roles     |
| Manage Nicknames    | Warframe IGN sync when linking Steam               |
| Manage Messages     | Purge, panels, embeds                              |
| Manage Threads      | Staff threads, event threads                       |
| Move Members        | Voice squad control                                |
| View Channels       | Read channels                                      |
| Connect / Speak     | Voice channels, music                              |
| Send Messages       | All bot messages                                   |
| Embed Links         | Rich embeds                                        |
| Attach Files        | Some commands                                      |
| Read Message History| Purge, snipe                                       |
| Add Reactions       | Reaction roles, RSVP                               |
| Use Slash Commands  | Required                                           |

Use the **OAuth2 → URL Generator** with scopes: `bot` and `applications.commands`.

---

## 3) Configure environment variables

Create a `.env` file in the `config/` folder (or set variables in your host, e.g. Railway).

### Required

| Variable          | Description                          |
|-------------------|--------------------------------------|
| `DISCORD_TOKEN`   | Your bot token from the Developer Portal |

### Recommended

| Variable                | Description                                  | Default              |
|-------------------------|----------------------------------------------|----------------------|
| `GUILD_ID`              | Your server ID (faster command sync)         | -                    |
| `TEMP_VC_CATEGORY_ID`   | Category ID for Temp VCs (join-to-create)    | -                    |
| `MOD_ROLE_NAME`         | Role name for mod-only commands              | `Obsidian Inheritor` |
| `TIMEZONE`              | For event/reminder parsing                   | `America/New_York`   |

### Optional – Channels (auto-created if `AUTO_SETUP=true`)

| Variable                    | Default           |
|-----------------------------|-------------------|
| `VOICE_PANEL_CHANNEL_ID`    | -                 |
| `VOICE_PANEL_CHANNEL_NAME`  | `obsidian-console`|
| `COMPLAINTS_CHANNEL_ID`     | -                 |
| `COMPLAINTS_CHANNEL_NAME`   | `inheritor-docket`|
| `COMPLAINTS_LOG_CHANNEL_ID` | -                 |
| `COMPLAINTS_LOG_CHANNEL_NAME`| `docket-ledger`  |
| `EVENTS_CHANNEL_ID`         | -                 |
| `EVENTS_CHANNEL_NAME`       | `ops-board`       |

### Optional – Voice / Temp VCs

| Variable                      | Default |
|-------------------------------|---------|
| `TEMP_VC_CATEGORY_NAME`       | `Temp VCs` |
| `CREATE_VC_NAME`              | `➕ Form Squad` |
| `VOICE_IDLE_DELETE_MINUTES`   | `5`     |
| `VC_CLEANUP_INTERVAL_MINUTES` | `2`     |

### Optional – Economy & XP

| Variable                    | Default |
|-----------------------------|---------|
| `ECONOMY_ENABLED`           | `true`  |
| `XP_ENABLED`                | `true`  |
| `COINS_PER_MESSAGE`         | `10`    |
| `XP_PER_MESSAGE`            | `20`    |
| `XP_PER_MINUTE_VOICE`       | `10`    |
| `XP_LEVEL_MULTIPLIER`       | `100`   |
| `XP_LEVEL_EXPONENT`         | `2.25`  |

### Optional – Warframe & Steam

| Variable                 | Description                                                  |
|--------------------------|--------------------------------------------------------------|
| `STEAM_API_KEY`          | Steam Web API key for Warframe playtime roles. [Get one](https://steamcommunity.com/dev/apikey) |
| `WARFRAME_MARKET_PROXY`  | HTTP(S) proxy URL if Warframe Market API returns 404 (e.g. on datacenter IPs) |

### Optional – Twitch

| Variable              | Description                          |
|-----------------------|--------------------------------------|
| `TWITCH_CLIENT_ID`    | For Warframe stream notifications    |
| `TWITCH_CLIENT_SECRET`| For Warframe stream notifications    |

### Optional – Other

| Variable                    | Default |
|-----------------------------|---------|
| `AUTO_SETUP`                | `true`  |
| `DB_PATH`                   | `data/obsidian_clanbot.db` |
| `EVENT_REMINDER_MINUTES_BEFORE` | `60` |
| `MESSAGE_COOLDOWN_SECONDS`  | `60`   |

---

## 4) Install and run

```bash
pip install -r deploy/requirements.txt
python run.py
```

**Railway / cloud:** See [DEPLOYMENT.md](DEPLOYMENT.md). **Project layout:** [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) (where to put new files). Folders: `bot/`, `commands/`, `core/`, `config/`, `data/`, `deploy/`, `docs/`. Root stays minimal; `requirements.txt` / `mise.toml` link into `deploy/` for Railpack. Use a persistent volume or external DB so data survives redeploys.

---

## 5) First-time setup

After the bot is online:

1. **Obsidian panels** (mods only)
   - Run `/setup_obsidian` in the channel where you want panels.

2. **Application system** (clan applications)
   - `/application_setup` action:Set Channel → choose channel
   - `/application_setup` action:Add Question → add questions via DM
   - `/application_setup` action:Post Panel → post the application panel

3. **XP level-up announcements** (optional)
   - `/xp_settings` channel:#level-ups → set channel for level-up messages

4. **Level roles** (optional)
   - `/level_roles` action:Add level:10 role:@Rising Star → assign roles at XP levels

5. **Warframe playtime roles** (optional, needs `STEAM_API_KEY`)
   - `/warframe_roles` action:Add achievement_type:Playtime hours:500 role:@Veteran Tenno
   - Users link with `/warframe_link` (Steam URL + Warframe in-game name)

6. **Warframe notifications** (Baro, alerts, etc.)
   - `/baro_notify` channel:#baro-alerts enabled:Enable
   - Similar notify commands for alerts, invasions, cycles, etc.

---

## Features Overview

| Category    | Features                                                                 |
|------------|---------------------------------------------------------------------------|
| **Voice**  | Join-to-create Temp VCs, squad control (rename/limit/lock/invite/transfer)|
| **Applications** | Clan application flow with questions, approval, Oathtaker role       |
| **Complaints**   | Docket cases, staff threads, DM updates                             |
| **Events** | Ops events, RSVP, reminders, event threads                               |
| **Economy**| Coins, daily, shop, pets, gambling                                       |
| **XP**     | Message/voice XP, levels, level-up announcements, level roles            |
| **Warframe**| Baro, alerts, invasions, cycles, LFG, trade search, playtime roles     |
| **Moderation**| Purge, warn, reaction roles, level roles, raid protection             |

---

## Key Commands

### General
- `/setup_obsidian` — Post Obsidian panels (mods)
- `/help` — Command list
- `/profile` — User profile
- `/achievements` — Unlocked achievements

### Applications
- `/application_setup` — Configure application system (mods)
- `/application` — Start application (in application channel)

### Economy & XP
- `/balance`, `/daily`, `/xp` — Economy and XP
- `/xp_settings` — Level-up announcement channel (mods)
- `/level_roles` — Roles at XP levels (mods)
- `/pet_shop`, `/pet_buy`, `/pet`, `/pet_feed`, `/pet_play` — Pets

### Warframe
- `/baro`, `/baro_notify` — Baro status and notifications
- `/warframe_link` — Link Steam + set nickname to IGN
- `/warframe_roles` — Playtime-based roles (mods)
- `/lfg`, `/lfg_list` — LFG
- `/trade_search`, `/trade_price` — Trade helpers

### Events
- `/event_create` — Create ops event with RSVP

### Moderation
- `/purge` — Clear messages
- `/warn` — Warn users
- `/reaction_roles` — Reaction role messages

---

## Notes

- **Mod role:** Commands marked "mods only" require Administrator (or the role named in `MOD_ROLE_NAME`).
- **Warframe link:** Users must set Steam profile and **Game details** to **Public** for playtime tracking.
- **Nickname sync:** Linking via `/warframe_link` sets the server nickname to the Warframe in-game name. The bot needs **Manage Nicknames**.
- **Warframe Market:** If `/trade_price` gets 404s on a server, set `WARFRAME_MARKET_PROXY` or `HTTPS_PROXY`.
- **Database:** Uses SQLite by default. For production, use a persistent volume or external database (see [RAILWAY_DATABASE.md](RAILWAY_DATABASE.md)).
