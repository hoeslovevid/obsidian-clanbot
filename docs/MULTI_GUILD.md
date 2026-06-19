# Multi-guild deployment

Obsidian Clan Bot is built for **many guilds** (global slash command sync). A single `GUILD_ID` is optional and no longer forces single-guild command registration.

## Command sync

| Setting | Behavior |
|---------|----------|
| **Default** (recommended for production) | `COMMAND_SYNC_GUILD_ONLY` unset or `false` → `tree.sync()` **globally**. New servers get commands within Discord's propagation window (often minutes, sometimes up to ~1 hour). |
| **Dev fast-sync** | `COMMAND_SYNC_GUILD_ONLY=true` **and** `GUILD_ID=<your test server>` → sync only to that guild on version bump. Use for local testing only. |

Sync runs when `BOT_VERSION` changes (see `data/.command_sync_version`). Mods can force sync with **`/admin sync_commands`**.

## New guild join

`on_guild_join` runs `ensure_core_channels` and join-to-create VC setup (`handlers/guild_events.py`). It does **not** per-guild sync commands — global commands already apply.

## Health check

**`/admin health`** shows:

- Registered command tree stats
- Sync scope (global vs dev guild)
- Total guild count
- Per-guild command usage heatmap (top + never-used)

## Railway / env checklist

```env
BOT_VERSION=2.0.0-alpha
# Do NOT set COMMAND_SYNC_GUILD_ONLY in production unless you intend dev-only sync
# GUILD_ID is optional — used for dev sync target or legacy tooling only
```

After a version bump, watch startup logs for `[sync] Synced globally`.

## Persistent data

Each guild's settings, economy, and moderation data are keyed by `guild_id` in SQLite. Use a **persistent volume** on Railway so `data/obsidian_clanbot.db` survives redeploys.

For high-scale multi-guild hosting, plan a move to Postgres (external DB URL) — not required for tens of guilds on SQLite with a volume.
